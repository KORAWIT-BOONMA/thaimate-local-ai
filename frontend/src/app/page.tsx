"use client";

import { useEffect, useRef, useState } from "react";

const API = "http://127.0.0.1:8000";
const GREETING = "สวัสดีครับ ผมคือ ThaiMate มีอะไรให้ช่วยไหม";
const MAX_RESULT_CHARS = 3000;

type Message = {
  role: "user" | "assistant";
  content: string;
};

type Conversation = {
  id: number;
  title: string;
  created_at: string;
};

type Part =
  | { type: "text"; text: string }
  | { type: "code"; lang: string; code: string };

type Preview = { command: string; cwd: string; timeout_seconds: number };
type RunResult = {
  exit_code: number | null;
  timed_out: boolean;
  stdout: string;
  stderr: string;
};

const LANG_EXT: Record<string, string> = {
  python: ".py",
  py: ".py",
  javascript: ".js",
  js: ".js",
  typescript: ".ts",
  ts: ".ts",
  tsx: ".tsx",
  jsx: ".jsx",
  json: ".json",
  html: ".html",
  css: ".css",
  markdown: ".md",
  md: ".md",
  text: ".txt",
  txt: ".txt",
};

function splitParts(content: string): Part[] {
  const parts: Part[] = [];
  const re = /```([^\n`]*)\n([\s\S]*?)```/g;
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(content)) !== null) {
    if (m.index > last) {
      parts.push({ type: "text", text: content.slice(last, m.index) });
    }
    parts.push({
      type: "code",
      lang: m[1].trim().toLowerCase(),
      code: m[2].replace(/\n$/, ""),
    });
    last = m.index + m[0].length;
  }
  if (last < content.length) {
    parts.push({ type: "text", text: content.slice(last) });
  }
  return parts;
}

function clip(text: string) {
  return text.length > MAX_RESULT_CHARS
    ? text.slice(0, MAX_RESULT_CHARS) + "\n...[ตัดข้อความที่ยาวเกิน]"
    : text;
}

// สร้างข้อความที่ส่งให้ AI จากผลการรัน
function buildResultMessage(path: string, r: RunResult) {
  const status = r.timed_out
    ? "หมดเวลา (timeout)"
    : `exit code ${r.exit_code}`;
  let msg = `ผลการรันไฟล์ ${path}: ${status}\n`;
  msg += `\nstdout:\n\`\`\`\n${clip(r.stdout) || "(ว่าง)"}\n\`\`\`\n`;
  if (r.stderr) {
    msg += `\nstderr:\n\`\`\`\n${clip(r.stderr)}\n\`\`\`\n`;
  }
  msg +=
    "\nช่วยตรวจผลลัพธ์นี้ ถ้าผลตรงตามที่ตั้งใจ ให้ตอบสั้นๆ 1-2 ประโยค และห้ามส่งโค้ดใหม่ " +
    "ถ้ามีข้อผิดพลาดจริง (เช่น traceback หรือ exit code ไม่ใช่ 0) ให้อธิบายสาเหตุ " +
    "แล้วส่งโค้ดฉบับเต็มที่แก้แล้วมาใน code block เดียว";
  return msg;
}

function CodeBlock({
  lang,
  code,
  canAct,
  onSaved,
  onSendResult,
}: {
  lang: string;
  code: string;
  canAct: boolean;
  onSaved: () => void;
  onSendResult: (text: string) => void;
}) {
  const isPython = lang === "python" || lang === "py";
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [status, setStatus] = useState("");
  const [needOverwrite, setNeedOverwrite] = useState(false);
  const [savedPath, setSavedPath] = useState<string | null>(null);

  const [preview, setPreview] = useState<Preview | null>(null);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<RunResult | null>(null);
  const [runError, setRunError] = useState("");

  function openDialog() {
    const ext = LANG_EXT[lang] ?? ".txt";
    setName(savedPath ?? `main${ext}`);
    setStatus("");
    setNeedOverwrite(false);
    setOpen(true);
  }

  async function save(overwrite: boolean) {
    setStatus("กำลังบันทึก...");
    try {
      const res = await fetch(`${API}/files/write`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: name.trim(), content: code, overwrite }),
      });
      const data = await res.json();
      if (res.status === 409) {
        setNeedOverwrite(true);
        setStatus(`ไฟล์ ${name.trim()} มีอยู่แล้ว ต้องการทับหรือไม่`);
        return;
      }
      if (!res.ok) {
        setNeedOverwrite(false);
        setStatus(`ไม่สำเร็จ: ${data.detail ?? "เกิดข้อผิดพลาด"}`);
        return;
      }
      setNeedOverwrite(false);
      setSavedPath(data.path);
      setPreview(null);
      setResult(null);
      setRunError("");
      setStatus(
        data.created
          ? `สร้างไฟล์ ${data.path} แล้ว`
          : `ทับไฟล์ ${data.path} แล้ว`
      );
      onSaved();
    } catch {
      setStatus("เชื่อมต่อ Backend ไม่ได้");
    }
  }

  async function requestRun() {
    if (!savedPath) return;
    setRunError("");
    setResult(null);
    try {
      const res = await fetch(
        `${API}/run/preview?path=${encodeURIComponent(savedPath)}`
      );
      const data = await res.json();
      if (!res.ok) {
        setRunError(data.detail ?? "ดูคำสั่งไม่สำเร็จ");
        return;
      }
      setPreview(data);
    } catch {
      setRunError("เชื่อมต่อ Backend ไม่ได้");
    }
  }

  async function approveRun() {
    if (!savedPath) return;
    setRunning(true);
    setRunError("");
    try {
      const res = await fetch(`${API}/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: savedPath, approved: true }),
      });
      const data = await res.json();
      if (!res.ok) {
        setRunError(data.detail ?? "รันไม่สำเร็จ");
      } else {
        setResult(data);
      }
      setPreview(null);
    } catch {
      setRunError("เชื่อมต่อ Backend ไม่ได้");
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="my-2 overflow-hidden rounded-lg border border-zinc-700 bg-zinc-950">
      <div className="flex items-center justify-between bg-zinc-900 px-3 py-1.5 text-xs text-zinc-400">
        <span>{lang || "code"}</span>
        {canAct && (
          <div className="flex gap-2">
            {isPython && savedPath && (
              <button
                onClick={requestRun}
                disabled={running}
                className="rounded bg-emerald-700 px-2 py-1 text-white hover:bg-emerald-600 disabled:opacity-60"
              >
                ▶ รันโค้ด
              </button>
            )}
            <button
              onClick={openDialog}
              className="rounded bg-zinc-800 px-2 py-1 text-zinc-200 hover:bg-zinc-700"
            >
              💾 บันทึกเป็นไฟล์
            </button>
          </div>
        )}
      </div>
      <pre className="overflow-x-auto p-3 text-sm">
        <code>{code}</code>
      </pre>

      {open && (
        <div className="border-t border-zinc-700 bg-zinc-900 p-3 text-sm">
          <p className="mb-2 text-zinc-300">
            บันทึกลง Workspace (โฟลเดอร์ <code>thaimate\workspace</code> เท่านั้น)
          </p>
          <div className="flex flex-wrap gap-2">
            <input
              value={name}
              onChange={(e) => {
                setName(e.target.value);
                setNeedOverwrite(false);
                setStatus("");
              }}
              className="min-w-0 flex-1 rounded bg-zinc-800 px-3 py-1.5 outline-none focus:ring-2 focus:ring-blue-600"
              placeholder="ชื่อไฟล์ เช่น main.py"
            />
            {needOverwrite ? (
              <button
                onClick={() => save(true)}
                className="rounded bg-red-600 px-3 py-1.5 font-medium hover:bg-red-500"
              >
                ยืนยันทับไฟล์เดิม
              </button>
            ) : (
              <button
                onClick={() => save(false)}
                disabled={!name.trim()}
                className="rounded bg-blue-600 px-3 py-1.5 font-medium hover:bg-blue-500 disabled:opacity-60"
              >
                ยืนยันบันทึก
              </button>
            )}
            <button
              onClick={() => setOpen(false)}
              className="rounded bg-zinc-800 px-3 py-1.5 hover:bg-zinc-700"
            >
              ปิด
            </button>
          </div>
          {status && <p className="mt-2 text-zinc-300">{status}</p>}
          {isPython && !savedPath && (
            <p className="mt-2 text-xs text-zinc-500">
              บันทึกไฟล์ก่อน แล้วปุ่ม ▶ รันโค้ด จะปรากฏ
            </p>
          )}
        </div>
      )}

      {preview && (
        <div className="border-t border-amber-700 bg-amber-950/40 p-3 text-sm">
          <p className="mb-2 font-medium text-amber-300">
            ตรวจสอบก่อนรัน: โค้ดจะถูกรันบนเครื่องของคุณจริง
          </p>
          <div className="mb-2 space-y-1 rounded bg-zinc-950 p-2 font-mono text-xs">
            <div>
              <span className="text-zinc-500">คำสั่ง: </span>
              {preview.command}
            </div>
            <div>
              <span className="text-zinc-500">โฟลเดอร์: </span>
              {preview.cwd}
            </div>
            <div>
              <span className="text-zinc-500">timeout: </span>
              {preview.timeout_seconds} วินาที
            </div>
          </div>
          <p className="mb-2 text-xs text-zinc-400">
            นี่ไม่ใช่ sandbox โค้ดที่รันทำได้ทุกอย่างที่บัญชีคุณทำได้
            อ่านโค้ดด้านบนให้เข้าใจก่อนกดอนุมัติ
          </p>
          <div className="flex gap-2">
            <button
              onClick={approveRun}
              className="rounded bg-emerald-600 px-3 py-1.5 font-medium hover:bg-emerald-500"
            >
              อนุมัติและรัน
            </button>
            <button
              onClick={() => setPreview(null)}
              className="rounded bg-zinc-800 px-3 py-1.5 hover:bg-zinc-700"
            >
              ยกเลิก
            </button>
          </div>
        </div>
      )}

      {running && (
        <div className="border-t border-zinc-700 p-3 text-sm text-zinc-300">
          กำลังรัน...
        </div>
      )}

      {runError && (
        <div className="border-t border-zinc-700 p-3 text-sm text-red-400">
          {runError}
        </div>
      )}

      {result && (
        <div className="border-t border-zinc-700 bg-zinc-900 p-3 text-sm">
          <p className="mb-2 text-xs text-zinc-400">
            ผลการรัน:{" "}
            {result.timed_out
              ? "หมดเวลา (timeout)"
              : `exit code ${result.exit_code}`}
          </p>
          {result.stdout && (
            <pre className="mb-2 max-h-64 overflow-auto whitespace-pre-wrap rounded bg-zinc-950 p-2 text-xs text-zinc-100">
              {result.stdout}
            </pre>
          )}
          {result.stderr && (
            <pre className="mb-2 max-h-64 overflow-auto whitespace-pre-wrap rounded bg-zinc-950 p-2 text-xs text-red-300">
              {result.stderr}
            </pre>
          )}
          {!result.stdout && !result.stderr && (
            <p className="mb-2 text-xs text-zinc-500">(ไม่มี output)</p>
          )}
          {savedPath && (
            <button
              onClick={() => onSendResult(buildResultMessage(savedPath, result))}
              disabled={!canAct}
              className="rounded bg-blue-600 px-3 py-1.5 text-xs font-medium hover:bg-blue-500 disabled:opacity-60"
            >
              📨 ส่งผลลัพธ์ให้ AI ดู
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function AssistantContent({
  content,
  canAct,
  onSaved,
  onSendResult,
}: {
  content: string;
  canAct: boolean;
  onSaved: () => void;
  onSendResult: (text: string) => void;
}) {
  return (
    <>
      {splitParts(content).map((p, i) =>
        p.type === "text" ? (
          <span key={i} className="whitespace-pre-wrap">
            {p.text}
          </span>
        ) : (
          <CodeBlock
            key={i}
            lang={p.lang}
            code={p.code}
            canAct={canAct}
            onSaved={onSaved}
            onSendResult={onSendResult}
          />
        )
      )}
    </>
  );
}

export default function Home() {
  const [messages, setMessages] = useState<Message[]>([
    { role: "assistant", content: GREETING },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [convId, setConvId] = useState<number | null>(null);
  const [files, setFiles] = useState<string[]>([]);
  const [attached, setAttached] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const sendingRef = useRef(false);

  async function refreshConversations() {
    try {
      const res = await fetch(`${API}/conversations`);
      if (res.ok) setConversations(await res.json());
    } catch {
      /* Backend ยังไม่รัน ข้ามไป */
    }
  }

  async function refreshFiles() {
    try {
      const res = await fetch(`${API}/files`);
      if (res.ok) setFiles(await res.json());
    } catch {}
  }

  async function openConversation(id: number) {
    try {
      const res = await fetch(`${API}/conversations/${id}/messages`);
      if (!res.ok) throw new Error();
      const data: Message[] = await res.json();
      setMessages([{ role: "assistant", content: GREETING }, ...data]);
      setConvId(id);
      try {
        localStorage.setItem("thaimate_conv_id", String(id));
      } catch {}
    } catch {
      newChat();
    }
  }

  function newChat() {
    setMessages([{ role: "assistant", content: GREETING }]);
    setConvId(null);
    setAttached(null);
    try {
      localStorage.removeItem("thaimate_conv_id");
    } catch {}
  }

  useEffect(() => {
    refreshConversations();
    refreshFiles();
    try {
      const saved = localStorage.getItem("thaimate_conv_id");
      if (saved) openConversation(Number(saved));
    } catch {}
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // override: ข้อความที่ส่งแทนช่องพิมพ์ (ใช้กับปุ่ม "ส่งผลลัพธ์ให้ AI ดู")
  async function handleSend(override?: string) {
    const fromButton = override !== undefined;
    const text = (fromButton ? override : input).trim();
    if (!text || loading || sendingRef.current) return;
    sendingRef.current = true;

    let content = text;
    if (!fromButton && attached) {
      try {
        const res = await fetch(
          `${API}/files/read?path=${encodeURIComponent(attached)}`
        );
        if (!res.ok) throw new Error();
        const data = await res.json();
        content = `${text}\n\n[ไฟล์แนบ: ${attached}]\n\`\`\`\n${data.content}\n\`\`\``;
      } catch {
        setMessages((prev) => [
          ...prev,
          { role: "assistant", content: `[อ่านไฟล์ ${attached} ไม่ได้]` },
        ]);
        sendingRef.current = false;
        return;
      }
    }

    const history: Message[] = [
      ...messages.slice(1),
      { role: "user", content },
    ];

    if (!fromButton) {
      setInput("");
      setAttached(null);
    }
    setLoading(true);
    setMessages((prev) => [
      ...prev,
      { role: "user", content },
      { role: "assistant", content: "" },
    ]);

    try {
      const res = await fetch(`${API}/chat/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ messages: history, conversation_id: convId }),
      });
      if (!res.ok || !res.body) throw new Error("Backend ตอบผิดปกติ");

      const idHeader = res.headers.get("X-Conversation-Id");
      if (idHeader) {
        const id = Number(idHeader);
        setConvId(id);
        try {
          localStorage.setItem("thaimate_conv_id", String(id));
        } catch {}
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        const chunk = decoder.decode(value, { stream: true });
        setMessages((prev) => {
          const copy = [...prev];
          const last = copy[copy.length - 1];
          copy[copy.length - 1] = { ...last, content: last.content + chunk };
          return copy;
        });
      }
    } catch {
      setMessages((prev) => {
        const copy = [...prev];
        copy[copy.length - 1] = {
          role: "assistant",
          content: "[เชื่อมต่อ Backend ไม่ได้ ตรวจว่า uvicorn รันอยู่]",
        };
        return copy;
      });
    } finally {
      sendingRef.current = false;
      setLoading(false);
      refreshConversations();
    }
  }

  return (
    <div className="flex h-screen bg-zinc-900 text-zinc-100">
      <aside className="hidden w-64 flex-col border-r border-zinc-800 bg-zinc-950 md:flex">
        <div className="p-3">
          <button
            onClick={newChat}
            disabled={loading}
            className="w-full rounded-xl bg-blue-600 px-4 py-2 font-medium hover:bg-blue-500 disabled:opacity-60"
          >
            + แชตใหม่
          </button>
        </div>
        <div className="flex-1 overflow-y-auto px-2 pb-4">
          {conversations.length === 0 && (
            <p className="px-2 py-4 text-sm text-zinc-500">ยังไม่มีประวัติ</p>
          )}
          {conversations.map((c) => (
            <button
              key={c.id}
              onClick={() => !loading && openConversation(c.id)}
              className={`mb-1 w-full truncate rounded-lg px-3 py-2 text-left text-sm hover:bg-zinc-800 ${
                c.id === convId ? "bg-zinc-800" : ""
              }`}
            >
              {c.title}
            </button>
          ))}
        </div>
      </aside>

      <main className="flex min-w-0 flex-1 flex-col">
        <header className="border-b border-zinc-800 px-6 py-4">
          <h1 className="text-lg font-semibold">ThaiMate AI</h1>
          <p className="text-sm text-zinc-400">ผู้ช่วย AI ภาษาไทยบนเครื่องของคุณ</p>
        </header>

        <div className="flex-1 overflow-y-auto px-4 py-6">
          <div className="mx-auto flex max-w-3xl flex-col gap-4">
            {messages.map((m, i) => {
              const isLast = i === messages.length - 1;
              const streaming = loading && isLast;
              return (
                <div
                  key={i}
                  className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}
                >
                  <div
                    className={`max-w-[80%] rounded-2xl px-4 py-3 ${
                      m.role === "user"
                        ? "max-h-96 overflow-auto whitespace-pre-wrap bg-blue-600 text-white"
                        : "min-w-0 bg-zinc-800"
                    }`}
                  >
                    {m.role === "user" ? (
                      m.content
                    ) : m.content ? (
                      <AssistantContent
                        content={m.content}
                        canAct={!loading}
                        onSaved={refreshFiles}
                        onSendResult={(t) => handleSend(t)}
                      />
                    ) : streaming ? (
                      "กำลังคิด..."
                    ) : (
                      ""
                    )}
                  </div>
                </div>
              );
            })}
            <div ref={bottomRef} />
          </div>
        </div>

        <div className="border-t border-zinc-800 px-4 py-4">
          <div className="mx-auto max-w-3xl">
            <div className="mb-2 flex flex-wrap items-center gap-2 text-sm">
              <select
                value=""
                onFocus={refreshFiles}
                onChange={(e) => e.target.value && setAttached(e.target.value)}
                disabled={loading}
                className="rounded-lg bg-zinc-800 px-3 py-1.5 outline-none"
              >
                <option value="">📎 แนบไฟล์จาก Workspace...</option>
                {files.map((f) => (
                  <option key={f} value={f}>
                    {f}
                  </option>
                ))}
              </select>
              {attached && (
                <span className="flex items-center gap-2 rounded-lg bg-zinc-800 px-3 py-1.5">
                  {attached}
                  <button
                    onClick={() => setAttached(null)}
                    className="text-zinc-400 hover:text-white"
                  >
                    ✕
                  </button>
                </span>
              )}
            </div>
            <div className="flex gap-2">
              <input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleSend()}
                placeholder="พิมพ์ข้อความ..."
                disabled={loading}
                className="flex-1 rounded-xl bg-zinc-800 px-4 py-3 outline-none focus:ring-2 focus:ring-blue-600 disabled:opacity-60"
              />
              <button
                onClick={() => handleSend()}
                disabled={loading}
                className="rounded-xl bg-blue-600 px-5 py-3 font-medium hover:bg-blue-500 disabled:opacity-60"
              >
                ส่ง
              </button>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}