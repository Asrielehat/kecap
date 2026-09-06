import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import ts from "typescript";
import assert from "node:assert/strict";

const source = fs.readFileSync(path.join(import.meta.dirname, "../src/lib/chat-stream.ts"), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
const sandbox = { exports: {}, TextDecoder, Error, JSON };
vm.runInNewContext(compiled, sandbox);
const { consumeStream } = sandbox.exports;

function body(text, step = 1) {
  const bytes = new TextEncoder().encode(text);
  return new ReadableStream({
    start(controller) {
      for (let i = 0; i < bytes.length; i += step) controller.enqueue(bytes.slice(i, i + step));
      controller.close();
    },
  });
}

const events = [];
await consumeStream(body(': ping\n\ndata: {"type":"token","data":"中文"}\n\ndata: {"type":"done","data":{"status":"complete"}}\n\n'), event => events.push(event));
assert.equal(events[0].data, "中文");
assert.equal(events[1].type, "done");
await assert.rejects(consumeStream(body('data: {"type":"token","data":"partial"}\n\n'), () => {}), /连接中断/);
const failed = [];
await consumeStream(body('data: {"type":"error","data":"失败"}\r\n\r\ndata: {"type":"done","data":{"status":"failed"}}\r\n\r\n'), event => failed.push(event));
assert.equal(failed[0].type, "error");
assert.equal(failed[1].data.status, "failed");
console.log("3 stream protocol tests passed (UTF-8 split, disconnect, error/CRLF).");
