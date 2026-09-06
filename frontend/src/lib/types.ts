export interface Message {
  id?: string;
  clientId?: string;
  status?: string;
  error?: string;
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  agentTrace?: AgentTraceStep[];
  reasoning?: string;       // 深度思考推理链（流式累积，仅本次会话保留）
  reasoningOpen?: boolean;  // 深度思考面板展开态（流式后保留，用户可自由收/放）
  streaming?: boolean;   // 流式生成中：思考面板实时展开、隐藏"思考中"占位
  traceOpen?: boolean;   // 思考面板展开态（流式后保留，用户可自由收/放）
}

/** Agent 运行轨迹单步：规划 / 检索轮次 / MCP 工具调用 / 兜底 / 自检 */
export interface AgentTraceStep {
  step: number;
  type: "plan" | "retrieval" | "tool" | "fallback" | "selfcheck";
  query?: string;
  top_k?: number;
  hits?: number;
  scores?: number[];
  preview?: string;
  content?: string;
  sub_questions?: string[];
  tool?: string;
  args?: string;
  ok?: boolean;
  result_chars?: number;
  note?: string;
}

export interface Citation {
  text: string;
  document_name: string;
  page?: number;
  chunk_id: string;
  score: number;
}

export interface Course {
  id: string;
  name: string;
  document_count: number;
}

export interface ConversationItem {
  id: string;
  course_id: string;
  title: string;
  created_at: string;
}

export interface FollowUpModalState {
  id: string;
  followUpId?: string; // 后端返回的 FollowUp 记录 ID，用于嵌套追问
  selectedText: string;
  contextParagraph: string;
  messageId: string;
  answer: string;
  citations: Citation[];
  loading: boolean;
  x: number;
  y: number;
  zIndex: number;
}

// 对话框内的一轮问答（question 为 null 表示自动解释轮）
export interface FollowUpTurn {
  id: string;               // 客户端 turn id（对话框内区分轮次）
  followUpId?: string;      // 后端 FollowUp 记录 id（嵌套追问的 parent_follow_up_id 用这个）
  question: string | null;  // 用户该轮的问题；自动解释轮为 null
  answer: string;
  citations: Citation[];
  loading: boolean;
}

// 智能提问对话框：框选文字后打开，问答可无限叠加
export interface FollowUpDialogState {
  id: string;
  selectedText: string;     // 对话框锚点：主消息区选中的文字
  contextParagraph: string;
  messageId: string;        // 被追问的 assistant 消息 id（第一轮 POST 用）
  turns: FollowUpTurn[];
  x: number;
  y: number;
  zIndex: number;
}
