import type { Citation, AgentTraceStep } from "./types";

export type StreamEvent =
  | { type: "session"; conversation_id: string; user_message_id: string }
  | { type: "token" | "reasoning" | "error" | "status"; data: string }
  | { type: "trace"; data: AgentTraceStep }
  | { type: "citations"; data: Citation[] }
  | { type: "done"; data: { assistant_message_id: string; status: string } };

export async function consumeStream(body: ReadableStream<Uint8Array>, onEvent: (event: StreamEvent) => void) {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let completed = false;
  try {
    while (true) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      buffer = buffer.replace(/\r\n/g, "\n");
      let boundary: number;
      while ((boundary = buffer.indexOf("\n\n")) >= 0) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const data = frame.split("\n").filter(line => line.startsWith("data:")).map(line => line.slice(5).trimStart()).join("\n");
        if (!data) continue;
        const event = JSON.parse(data) as StreamEvent;
        onEvent(event);
        if (event.type === "done") completed = true;
      }
      if (done) break;
    }
    if (!completed) throw new Error("连接中断，回答尚未完成，可以重试");
  } finally {
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}
