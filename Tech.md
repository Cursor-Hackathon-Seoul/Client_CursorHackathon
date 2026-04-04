# IdeaStorm 아키텍처 패턴 레퍼런스
> 타 프로젝트 적용을 위한 멀티에이전트 대화 + LLM 연동 가이드

---

## Part 1. 멀티에이전트 대화 패턴

### 1.1 에이전트 역할 아키텍처

IdeaStorm은 3종류의 참가자로 구성된다. 이 구조를 그대로 추상화하면 어떤 멀티에이전트 시스템에도 적용 가능하다.

```
┌─────────────────────────────────────────────────┐
│                  세션 (Session)                   │
│                                                   │
│   ┌───────────────────────────────────┐          │
│   │  Orchestrator (Facilitator 역할)   │          │
│   │  - 세션 흐름 제어                   │          │
│   │  - 단계 전환 결정                   │          │
│   │  - 충돌 중재 + 요약                 │          │
│   │  - 투표/수렴 진행                   │          │
│   │  ★ 직접 콘텐츠 생성하지 않음        │          │
│   └──────────┬────────────────────────┘          │
│              │ 지시/요약/전환                      │
│   ┌──────────▼────────────────────────┐          │
│   │  Persona Agents (N개)              │          │
│   │  - 각자 고유 시스템 프롬프트 보유   │          │
│   │  - 자기 관점에서만 발언             │          │
│   │  - 타 에이전트 발언에 반응 가능     │          │
│   └──────────┬────────────────────────┘          │
│              │ 동등한 참가자                       │
│   ┌──────────▼────────────────────────┐          │
│   │  Human User                        │          │
│   │  - 에이전트와 동등한 참가자         │          │
│   │  - Override 권한 보유               │          │
│   │  - 패스(발언 스킵) 가능             │          │
│   └───────────────────────────────────┘          │
└─────────────────────────────────────────────────┘
```

#### 핵심 설계 원칙

| 원칙 | 설명 | 적용 방법 |
|------|------|----------|
| **Orchestrator ≠ 참가자** | 진행자는 콘텐츠를 생성하지 않고 프로세스만 관리 | 별도 시스템 프롬프트에 "아이디어를 직접 제안하지 마라" 명시 |
| **페르소나 격리** | 각 에이전트는 자기 관점에서만 발언 | 에이전트별 독립 시스템 프롬프트 + 역할 제약 |
| **사용자 = 참가자** | 사용자를 진행자가 아닌 동등한 참가자로 | Override만 추가 권한, 나머진 에이전트와 동일 |

---

### 1.2 에이전트 간 대화 프로토콜

#### 메시지 구조

```typescript
interface AgentMessage {
  id: string;
  sessionId: string;
  phase: Phase;          // PHASE_1 | PHASE_2 | PHASE_3 | PHASE_4
  round: Round;          // DIVERGE | REACT | CONVERGE
  sender: Sender;        // { type: 'orchestrator' | 'agent' | 'user', id: string }
  content: string;
  replyTo?: string;      // 반응 대상 메시지 ID (Round 2에서 사용)
  metadata: {
    personaId?: string;  // 어떤 페르소나가 발언했는지
    reactionType?: 'agree_extend' | 'counter' | 'combine' | 'deepen';
    maxLength: number;   // 발언 길이 제한 (토큰/글자)
    timestamp: number;
  };
}
```

#### 발언 순서 제어 (Turn Management)

```typescript
interface TurnManager {
  currentPhase: Phase;
  currentRound: Round;
  turnQueue: string[];        // 발언 대기열 [agent1, agent2, ..., user]
  currentSpeaker: string;
  silenceTimer: number;       // 침묵 감지 타이머 (ms)

  // 라운드별 침묵 감지 기준
  silenceThresholds: {
    DIVERGE: { detect: 15000, autoAdvance: 30000 },
    REACT:   { detect: 10000, autoAdvance: 20000 },
    CONVERGE: null  // 투표 완료 즉시 전환
  };
}
```

**순차 발언 흐름**:

```
1. Orchestrator → 라운드 시작 선언 + 프롬프트 제시
2. Agent[0] → 발언 (1.5초 딜레이 후)
3. Agent[1] → 발언 (이전 발언 컨텍스트 포함)
4. Agent[2] → 발언
5. ...Agent[N]
6. User → 발언 or 패스
7. Orchestrator → 전체 요약 → 다음 라운드 전환
```

각 에이전트의 LLM 호출 시 **이전 발언들을 컨텍스트로 주입**하는 것이 핵심:

```typescript
async function generateAgentResponse(
  agent: PersonaAgent,
  conversationHistory: AgentMessage[],
  currentPhase: Phase,
  currentRound: Round
): Promise<string> {
  const systemPrompt = buildSystemPrompt(agent.persona, currentPhase, currentRound);
  const contextMessages = conversationHistory.map(msg => ({
    role: msg.sender.type === 'user' ? 'user' : 'assistant',
    content: `[${msg.sender.id}] ${msg.content}`
  }));

  const response = await llmClient.chat({
    model: agent.model,
    system: systemPrompt,
    messages: [
      ...contextMessages,
      { role: 'user', content: buildTurnPrompt(agent, currentRound) }
    ],
    max_tokens: getMaxTokens(currentRound)
  });

  return response.content;
}
```

---

### 1.3 3라운드 수렴 메커니즘 (재사용 가능한 패턴)

모든 의사결정 단계에서 반복 적용 가능한 **발산→반응→수렴** 패턴:

```typescript
interface ConvergenceRound<T> {
  // Round 1: 발산
  diverge(participants: Participant[]): T[];

  // Round 2: 반응
  react(items: T[], participants: Participant[]): ReactedItem<T>[];

  // Round 3: 수렴
  converge(
    items: ReactedItem<T>[],
    orchestrator: Orchestrator
  ): { candidates: T[]; votes: Vote[]; selected: T };
}

interface Vote {
  voterId: string;
  candidateId: string;
  reason: string;       // 50자 이내
}

// 투표 로직
function resolveVote(votes: Vote[], candidates: string[]): string {
  const tally = candidates.map(c => ({
    candidate: c,
    count: votes.filter(v => v.candidateId === c).length
  }));

  const sorted = tally.sort((a, b) => b.count - a.count);
  const majority = Math.ceil(votes.length / 2);

  if (sorted[0].count >= majority) {
    return sorted[0].candidate; // 과반 득표
  }

  // 결선 투표: 상위 2개로 재투표
  return runoff(sorted.slice(0, 2), votes);
}
```

**어디에 적용할 수 있나**:
- 팀 의사결정 도구
- AI 기반 설문/합의 시스템
- 코드 리뷰에서 여러 AI 리뷰어의 의견 수렴
- 콘텐츠 생성에서 여러 관점의 초안 → 최종 선택

---

### 1.4 에이전트 간 상호작용 유형

```typescript
enum ReactionType {
  AGREE_EXTEND = 'agree_extend',  // 동의 + 확장
  COUNTER = 'counter',            // 반박
  COMBINE = 'combine',            // 결합 제안
  DEEPEN = 'deepen'               // 질문 심화
}

// 반응 생성 시 시스템 프롬프트에 명시적으로 유형 지정
const reactionSystemPrompt = `
당신은 ${persona.name}입니다. ${persona.description}

다른 참가자의 발언에 반응하세요.
반응 유형 중 하나를 선택하고 그에 맞게 답변하세요:
- 동의+확장: 상대 아이디어에 동의하면서 더 발전시킴
- 반박: 약점이나 리스크를 지적
- 결합: 두 가지 아이디어를 합쳐 새로운 방향 제안
- 질문심화: 더 깊은 탐색을 위한 후속 질문

${roundConstraints.maxLength}자 이내로 답변하세요.
`;
```

#### 충돌 감지 및 중재

```typescript
interface ConflictDetector {
  detect(messages: AgentMessage[]): Conflict | null;
  summarize(conflict: Conflict): string;
  delegateToUser(conflict: Conflict): UserPrompt;
}

// Orchestrator가 충돌 감지 시:
// 1. "충돌 감지" 선언
// 2. 양측 주장 요약
// 3. 사용자에게 방향 선택 위임
```

---

### 1.5 페르소나 시스템 프롬프트 설계 패턴

```typescript
interface PersonaConfig {
  id: string;
  name: string;
  emoji: string;
  color: string;           // UI 포스트잇 색상
  systemPrompt: string;
  constraints: {
    perspective: string;   // "기술 실현성 관점에서만 발언"
    tone: string;          // "실용적이고 구체적"
    forbidden: string[];   // ["다른 관점 침범 금지", "직접 결론 내지 않기"]
  };
}

// 예시: 스타트업 팀 셋
const startupTeamSet: PersonaConfig[] = [
  {
    id: 'ceo',
    name: '비저너리 CEO',
    emoji: '🟡',
    color: '#FFD700',
    systemPrompt: `당신은 장기 비전을 가진 CEO입니다.
모든 아이디어를 "10년 후 어떻게 될까?"의 관점에서 바라봅니다.
시장 규모, 비전, 확장 가능성에 집중하세요.`,
    constraints: {
      perspective: '장기 비전과 시장 기회',
      tone: '열정적이고 큰 그림 중심',
      forbidden: ['기술 구현 세부사항', 'UX 디테일']
    }
  },
  // ... 나머지 에이전트
];
```

#### 페르소나 셋을 모듈화하는 방법

```typescript
// 셋 단위로 관리 — 프로젝트별로 셋만 교체하면 됨
interface PersonaSet {
  id: string;
  name: string;
  description: string;
  recommendedFor: string;
  personas: PersonaConfig[];
}

const personaSets: Record<string, PersonaSet> = {
  disney: { /* 몽상가, 현실주의자, 비평가 */ },
  startup: { /* CEO, 투자자, UX, 개발자 */ },
  userSpectrum: { /* 얼리어답터, 저항자, 파워, 캐주얼 */ },
};
```

---

## Part 2. LLM 구독 툴 연동 패턴

### 2.1 아키텍처 개요

```
┌──────────────────────────────────────────────────────┐
│                   클라이언트 (Frontend)                │
│                                                       │
│  ┌─────────────┐  ┌─────────────┐  ┌──────────────┐ │
│  │ OAuth 버튼   │  │ API Key 입력 │  │ 모델 선택 UI  │ │
│  └──────┬──────┘  └──────┬──────┘  └──────┬───────┘ │
└─────────┼────────────────┼────────────────┼──────────┘
          │                │                │
          ▼                ▼                ▼
┌──────────────────────────────────────────────────────┐
│                   서버 (Backend)                      │
│                                                       │
│  ┌────────────────────────────────────────────┐      │
│  │           Auth Manager                      │      │
│  │  - OAuth 토큰 관리 (자동 갱신)              │      │
│  │  - API Key 저장 (암호화)                    │      │
│  │  - 인증 상태 확인                           │      │
│  └──────────────────┬─────────────────────────┘      │
│                     │                                 │
│  ┌──────────────────▼─────────────────────────┐      │
│  │           Model Router                      │      │
│  │  - 모델별 API 엔드포인트 라우팅             │      │
│  │  - 에이전트별 모델 배정 (추후)              │      │
│  │  - 폴백 처리                                │      │
│  └──────────────────┬─────────────────────────┘      │
│                     │                                 │
│  ┌──────────────────▼─────────────────────────┐      │
│  │        LLM Provider Adapters                │      │
│  │  ┌─────────┐ ┌─────────┐ ┌──────────────┐ │      │
│  │  │Anthropic│ │ Google  │ │   OpenAI     │ │      │
│  │  │ Claude  │ │ Gemini  │ │   Codex      │ │      │
│  │  └─────────┘ └─────────┘ └──────────────┘ │      │
│  │  ┌─────────┐ ┌─────────┐                  │      │
│  │  │Moonshot │ │Anysphere│                  │      │
│  │  │  Kimi   │ │ Cursor  │                  │      │
│  │  └─────────┘ └─────────┘                  │      │
│  └────────────────────────────────────────────┘      │
└──────────────────────────────────────────────────────┘
```

### 2.2 인증 매니저 (Auth Manager)

두 가지 인증 방식을 통합 관리:

```typescript
// --- 인증 방식 정의 ---

interface AuthConfig {
  provider: LLMProvider;
  method: 'oauth' | 'api_key';
  oauth?: OAuthConfig;
  apiKey?: ApiKeyConfig;
}

interface OAuthConfig {
  authorizationUrl: string;
  tokenUrl: string;
  clientId: string;
  clientSecret: string;       // 서버 사이드 보관
  scopes: string[];
  redirectUri: string;
}

interface ApiKeyConfig {
  storageMode: 'local' | 'server_encrypted';
  encryptionKey?: string;
}

// --- 프로바이더별 설정 ---

const providerAuthConfigs: Record<LLMProvider, AuthConfig> = {
  anthropic: {
    provider: 'anthropic',
    method: 'oauth',          // OAuth 우선
    oauth: {
      authorizationUrl: 'https://console.anthropic.com/oauth/authorize',
      tokenUrl: 'https://console.anthropic.com/oauth/token',
      clientId: process.env.ANTHROPIC_CLIENT_ID!,
      clientSecret: process.env.ANTHROPIC_CLIENT_SECRET!,
      scopes: ['model:read', 'model:write'],
      redirectUri: `${BASE_URL}/auth/callback/anthropic`
    },
    apiKey: { storageMode: 'local' }  // 대안
  },

  google: {
    provider: 'google',
    method: 'oauth',
    oauth: {
      authorizationUrl: 'https://accounts.google.com/o/oauth2/v2/auth',
      tokenUrl: 'https://oauth2.googleapis.com/token',
      clientId: process.env.GOOGLE_CLIENT_ID!,
      clientSecret: process.env.GOOGLE_CLIENT_SECRET!,
      scopes: ['https://www.googleapis.com/auth/generative-language'],
      redirectUri: `${BASE_URL}/auth/callback/google`
    },
    apiKey: { storageMode: 'local' }
  },

  openai: {
    provider: 'openai',
    method: 'oauth',
    oauth: { /* ... */ },
    apiKey: { storageMode: 'local' }
  },

  moonshot: {
    provider: 'moonshot',
    method: 'api_key',       // OAuth 미지원 — API Key만
    apiKey: { storageMode: 'local' }
  },

  anysphere: {
    provider: 'anysphere',
    method: 'oauth',
    oauth: { /* ... */ }
    // API Key 미지원
  }
};
```

#### OAuth 플로우 구현

```typescript
class OAuthManager {
  // Step 1: 인증 URL 생성
  getAuthorizationUrl(provider: LLMProvider): string {
    const config = providerAuthConfigs[provider].oauth!;
    const state = crypto.randomUUID(); // CSRF 방지
    this.stateStore.set(state, { provider, timestamp: Date.now() });

    const params = new URLSearchParams({
      client_id: config.clientId,
      redirect_uri: config.redirectUri,
      response_type: 'code',
      scope: config.scopes.join(' '),
      state
    });

    return `${config.authorizationUrl}?${params}`;
  }

  // Step 2: 콜백 처리 → 토큰 교환
  async handleCallback(code: string, state: string): Promise<TokenPair> {
    const stateData = this.stateStore.get(state);
    if (!stateData) throw new Error('Invalid state');

    const config = providerAuthConfigs[stateData.provider].oauth!;

    const response = await fetch(config.tokenUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({
        grant_type: 'authorization_code',
        code,
        redirect_uri: config.redirectUri,
        client_id: config.clientId,
        client_secret: config.clientSecret
      })
    });

    const tokens: TokenPair = await response.json();
    await this.tokenStore.save(stateData.provider, tokens);
    return tokens;
  }

  // Step 3: 토큰 자동 갱신
  async getValidToken(provider: LLMProvider): Promise<string> {
    const tokens = await this.tokenStore.get(provider);
    if (!tokens) throw new Error('Not authenticated');

    if (this.isExpired(tokens)) {
      const refreshed = await this.refreshToken(provider, tokens.refresh_token);
      await this.tokenStore.save(provider, refreshed);
      return refreshed.access_token;
    }

    return tokens.access_token;
  }
}
```

#### API Key 관리 (클라이언트 사이드 저장)

```typescript
class ApiKeyManager {
  // 보안: 서버로 전송하지 않고 로컬 스토리지에 암호화 저장
  saveKey(provider: LLMProvider, apiKey: string): void {
    const encrypted = this.encrypt(apiKey);
    localStorage.setItem(`llm_key_${provider}`, encrypted);
  }

  getKey(provider: LLMProvider): string | null {
    const encrypted = localStorage.getItem(`llm_key_${provider}`);
    if (!encrypted) return null;
    return this.decrypt(encrypted);
  }

  // API Key 유효성 검증
  async validateKey(provider: LLMProvider, apiKey: string): Promise<boolean> {
    try {
      const adapter = this.getAdapter(provider);
      await adapter.testConnection(apiKey);
      return true;
    } catch {
      return false;
    }
  }
}
```

---

### 2.3 모델 라우터 (Model Router)

사용자가 선택한 모델에 따라 적절한 프로바이더 어댑터로 라우팅:

```typescript
interface ModelConfig {
  id: string;
  provider: LLMProvider;
  displayName: string;
  tier: 'fast' | 'balanced' | 'powerful';
  maxTokens: number;
  supportedAuthMethods: ('oauth' | 'api_key')[];
}

const availableModels: ModelConfig[] = [
  {
    id: 'claude-sonnet-4',
    provider: 'anthropic',
    displayName: 'Claude Sonnet 4',
    tier: 'balanced',
    maxTokens: 8192,
    supportedAuthMethods: ['oauth', 'api_key']
  },
  {
    id: 'claude-opus-4',
    provider: 'anthropic',
    displayName: 'Claude Opus 4',
    tier: 'powerful',
    maxTokens: 8192,
    supportedAuthMethods: ['oauth', 'api_key']
  },
  {
    id: 'gemini-2.0-flash',
    provider: 'google',
    displayName: 'Gemini 2.0 Flash',
    tier: 'fast',
    maxTokens: 8192,
    supportedAuthMethods: ['oauth', 'api_key']
  },
  {
    id: 'gemini-2.5-pro',
    provider: 'google',
    displayName: 'Gemini 2.5 Pro',
    tier: 'powerful',
    maxTokens: 8192,
    supportedAuthMethods: ['oauth', 'api_key']
  },
  // ... Codex, Kimi, Cursor
];

class ModelRouter {
  private adapters: Map<LLMProvider, LLMAdapter>;

  async chat(
    modelId: string,
    messages: ChatMessage[],
    options?: ChatOptions
  ): Promise<ChatResponse> {
    const model = availableModels.find(m => m.id === modelId);
    if (!model) throw new Error(`Unknown model: ${modelId}`);

    const adapter = this.adapters.get(model.provider);
    if (!adapter) throw new Error(`No adapter for: ${model.provider}`);

    const credential = await this.resolveCredential(model);

    return adapter.chat(model.id, credential, messages, options);
  }

  private async resolveCredential(model: ModelConfig): Promise<Credential> {
    // OAuth 토큰 우선 → 없으면 API Key 폴백
    try {
      const token = await this.oauthManager.getValidToken(model.provider);
      return { type: 'oauth', token };
    } catch {
      const apiKey = this.apiKeyManager.getKey(model.provider);
      if (apiKey) return { type: 'api_key', key: apiKey };
      throw new Error(`No credentials for ${model.provider}`);
    }
  }
}
```

---

### 2.4 LLM 프로바이더 어댑터 (통합 인터페이스)

모든 LLM 프로바이더를 하나의 인터페이스로 추상화:

```typescript
interface LLMAdapter {
  provider: LLMProvider;
  chat(
    modelId: string,
    credential: Credential,
    messages: ChatMessage[],
    options?: ChatOptions
  ): Promise<ChatResponse>;
  stream(
    modelId: string,
    credential: Credential,
    messages: ChatMessage[],
    options?: ChatOptions
  ): AsyncIterable<ChatChunk>;
  testConnection(credential: Credential): Promise<boolean>;
}

// 통합 메시지 포맷 → 프로바이더별 변환
interface ChatMessage {
  role: 'system' | 'user' | 'assistant';
  content: string;
}

// --- Anthropic 어댑터 예시 ---

class AnthropicAdapter implements LLMAdapter {
  provider = 'anthropic' as const;

  async chat(modelId, credential, messages, options) {
    const systemMsg = messages.find(m => m.role === 'system');
    const chatMsgs = messages.filter(m => m.role !== 'system');

    const response = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(credential.type === 'api_key'
          ? { 'x-api-key': credential.key, 'anthropic-version': '2023-06-01' }
          : { 'Authorization': `Bearer ${credential.token}` }
        )
      },
      body: JSON.stringify({
        model: modelId,
        system: systemMsg?.content,
        messages: chatMsgs.map(m => ({ role: m.role, content: m.content })),
        max_tokens: options?.maxTokens ?? 1024
      })
    });

    return this.parseResponse(await response.json());
  }
}

// --- Google 어댑터 예시 ---

class GoogleAdapter implements LLMAdapter {
  provider = 'google' as const;

  async chat(modelId, credential, messages, options) {
    const url = credential.type === 'api_key'
      ? `https://generativelanguage.googleapis.com/v1beta/models/${modelId}:generateContent?key=${credential.key}`
      : `https://generativelanguage.googleapis.com/v1beta/models/${modelId}:generateContent`;

    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (credential.type === 'oauth') {
      headers['Authorization'] = `Bearer ${credential.token}`;
    }

    const response = await fetch(url, {
      method: 'POST',
      headers,
      body: JSON.stringify({
        contents: this.convertMessages(messages),
        generationConfig: { maxOutputTokens: options?.maxTokens ?? 1024 }
      })
    });

    return this.parseResponse(await response.json());
  }
}
```

---

### 2.5 에이전트별 모델 배정 (Advanced)

MVP 이후, 에이전트 역할에 따라 서로 다른 모델을 배정하는 패턴:

```typescript
interface AgentModelAssignment {
  agentRole: 'orchestrator' | 'persona' | 'clustering';
  modelId: string;
  reason: string;
}

// 역할별 추천 배정
const defaultAssignments: AgentModelAssignment[] = [
  {
    agentRole: 'orchestrator',
    modelId: 'claude-opus-4',
    reason: '문맥 파악·중재 능력 최우선'
  },
  {
    agentRole: 'persona',
    modelId: 'claude-sonnet-4',
    reason: '빠른 응답, 비용 효율'
  },
  {
    agentRole: 'clustering',
    modelId: 'gemini-2.5-pro',
    reason: '구조화 출력에 강점'
  }
];

class MultiModelOrchestrator {
  private router: ModelRouter;
  private assignments: Map<string, string>; // agentId → modelId

  async generateForAgent(
    agentId: string,
    agentRole: string,
    messages: ChatMessage[]
  ): Promise<string> {
    const modelId = this.assignments.get(agentId)
      ?? this.getDefaultModel(agentRole);

    const response = await this.router.chat(modelId, messages);
    return response.content;
  }
}
```

---

## Part 3. 타 프로젝트 적용 체크리스트

### 3.1 멀티에이전트 대화 적용 시

```
□ 1. 역할 분리
    □ Orchestrator (진행/중재)와 Participant (콘텐츠 생성) 분리했는가?
    □ 각 에이전트의 시스템 프롬프트에 역할 제약이 명확한가?

□ 2. 대화 프로토콜
    □ 발언 순서 관리 (Turn Management) 구현했는가?
    □ 에이전트 간 컨텍스트 공유 방식 정의했는가?
    □ 발언 길이 제한을 라운드별로 설정했는가?

□ 3. 수렴 메커니즘
    □ 발산→반응→수렴 3라운드 구조를 적용했는가?
    □ 투표/합의 로직이 있는가?
    □ 사용자 Override 권한이 있는가?

□ 4. 상호작용
    □ 반응 유형 (동의/반박/결합/심화)을 정의했는가?
    □ 충돌 감지 및 중재 로직이 있는가?
    □ 침묵 감지 기반 자동 전환이 있는가?

□ 5. 페르소나
    □ 페르소나를 셋 단위로 모듈화했는가?
    □ 프로젝트 도메인에 맞는 페르소나 셋을 설계했는가?
```

### 3.2 LLM 연동 적용 시

```
□ 1. 인증
    □ OAuth + API Key 이중 인증 지원하는가?
    □ 토큰 자동 갱신 로직이 있는가?
    □ API Key는 클라이언트 사이드에서 암호화 저장하는가?

□ 2. 모델 라우팅
    □ 통합 LLM 인터페이스 (Adapter 패턴)를 사용하는가?
    □ 프로바이더별 메시지 포맷 변환이 구현되었는가?
    □ 인증 방식에 따른 헤더 분기 처리가 되었는가?

□ 3. 비용 모델
    □ 사용자 계정의 크레딧을 사용하는 구조인가? (서비스가 비용 부담 안 함)
    □ 모델 tier (fast/balanced/powerful) 선택지를 제공하는가?

□ 4. 확장성
    □ 새 프로바이더 추가 시 Adapter만 구현하면 되는 구조인가?
    □ 에이전트별 모델 배정을 지원할 수 있는 구조인가?
```

---

## Part 4. 최소 구현 예시 (Skeleton)

타 프로젝트에 바로 붙일 수 있는 최소 코드 구조:

```
src/
├── agents/
│   ├── orchestrator.ts       # Facilitator 에이전트
│   ├── persona-agent.ts      # 페르소나 에이전트 클래스
│   ├── persona-sets/         # 페르소나 셋 정의
│   │   ├── disney.ts
│   │   ├── startup.ts
│   │   └── user-spectrum.ts
│   └── turn-manager.ts       # 발언 순서 + 침묵 감지
│
├── llm/
│   ├── auth-manager.ts       # OAuth + API Key 통합 인증
│   ├── model-router.ts       # 모델 선택 → 어댑터 라우팅
│   ├── adapters/
│   │   ├── adapter.interface.ts  # 통합 인터페이스
│   │   ├── anthropic.ts
│   │   ├── google.ts
│   │   ├── openai.ts
│   │   ├── moonshot.ts
│   │   └── anysphere.ts
│   └── models.ts             # 사용 가능한 모델 목록
│
├── convergence/
│   ├── round-manager.ts      # 3라운드 수렴 엔진
│   ├── vote.ts               # 투표 로직
│   └── conflict-detector.ts  # 충돌 감지
│
└── session/
    ├── session.ts             # 세션 상태 관리
    ├── message.ts             # 메시지 타입 정의
    └── phase-manager.ts       # Phase 전환 로직
```

---

*이 문서는 IdeaStorm PRD v1.1을 기반으로 멀티에이전트 대화 패턴과 LLM 연동 방법을 추출·정리한 레퍼런스입니다.*
