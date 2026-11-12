"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import AssistantTools from "./assistant-tools";

const API = "http://127.0.0.1:8000";
const GREETING = "สวัสดีครับ ผมคือ ThaiMate มีอะไรให้ช่วยไหม";
const MAX_RESULT_CHARS = 3000;

type ChatImage = {
  mime_type: "image/png" | "image/jpeg" | "image/webp";
  data: string;
  name: string;
};

type Message = {
  role: "user" | "assistant";
  content: string;
  images?: ChatImage[];
};

function imageSource(image: ChatImage): string {
  return `data:${image.mime_type};base64,${image.data}`;
}

type ModelProvider = "ollama" | "gemini";

type Conversation = {
  id: number;
  title: string;
  created_at: string;
  model_provider?: ModelProvider;
};

type KnowledgeSource = {
  source: string;
  chunks: number;
  indexed_at: string;
};

type Part =
  | { type: "text"; text: string }
  | { type: "code"; lang: string; code: string };

type Preview = {
  command: string;
  cwd: string;
  timeout_seconds: number;
  execution_enabled?: boolean;
  warning?: string;
};

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

// ==========================================
// Split Text and Code
// ==========================================

function splitParts(content: string): Part[] {
  const parts: Part[] = [];
  const re = /```([^\n`]*)\n([\s\S]*?)```/g;

  let last = 0;
  let match: RegExpExecArray | null;

  while ((match = re.exec(content)) !== null) {
    if (match.index > last) {
      parts.push({
        type: "text",
        text: content.slice(last, match.index),
      });
    }

    parts.push({
      type: "code",
      lang: match[1].trim().toLowerCase(),
      code: match[2].replace(/\n$/, ""),
    });

    last = match.index + match[0].length;
  }

  if (last < content.length) {
    parts.push({
      type: "text",
      text: content.slice(last),
    });
  }

  return parts;
}

// ==========================================
// Rich Text and Citation Renderer
// ==========================================


function renderRichText(text: string): ReactNode[] {
  const nodes: ReactNode[] = [];

  const normalized = text.replace(
    /\\([`*_{}\[\]()#+.!>|~-])/g,
    "$1"
  );

  const regex =
    /(\[([^\]]+)\]\((https?:\/\/[^\s)]+)(?:\s+["'][^"']*["'])?\)|\[(W\d+|L\d+)\]|`([^`]+)`|\*\*([^\*]+)\*\*|(?<![A-Za-z0-9_])__([^_]+)__(?![A-Za-z0-9_])|\*([^\*\n]+)\*|(?<![A-Za-z0-9_])_([^_\n]+)_(?![A-Za-z0-9_])|(https?:\/\/[^\s<>)\]]+))/g;

  let lastIndex = 0;
  let match: RegExpExecArray | null;
  let key = 0;

  const pushText = (value: string) => {
    if (value) {
      nodes.push(
        <span key={`text-${key++}`}>{value}</span>
      );
    }
  };

  while ((match = regex.exec(normalized)) !== null) {
    pushText(normalized.slice(lastIndex, match.index));

    if (match[2] && match[3]) {
      nodes.push(
        <a
          key={`link-${key++}`}
          href={match[3]}
          target="_blank"
          rel="noopener noreferrer"
          title="เปิดเว็บไซต์ต้นทาง"
          className="text-blue-400 underline decoration-blue-400/40 underline-offset-2 break-all hover:text-blue-300"
        >
          {match[2]}
          <span className="ml-1 text-xs">↗</span>
        </a>
      );
    } else if (match[4]) {
      const citation = match[4];
      const isWeb = citation.startsWith("W");

      nodes.push(
        <span
          key={`citation-${key++}`}
          title={
            isWeb
              ? "แหล่งข้อมูลจากเว็บไซต์"
              : "เอกสารภายในเครื่อง"
          }
          className={`mx-0.5 inline-flex items-center rounded-md px-1.5 py-0.5 text-xs font-semibold align-middle ${
            isWeb
              ? "bg-blue-500/15 text-blue-400"
              : "bg-emerald-500/15 text-emerald-400"
          }`}
        >
          {citation}
        </span>
      );
    } else if (match[5]) {
      nodes.push(
        <code
          key={`inline-code-${key++}`}
          className="rounded bg-zinc-700/70 px-1.5 py-0.5 font-mono text-[0.9em] text-amber-200"
        >
          {match[5]}
        </code>
      );
    } else if (match[6] || match[7]) {
      nodes.push(
        <strong
          key={`bold-${key++}`}
          className="font-semibold text-zinc-100"
        >
          {match[6] ?? match[7]}
        </strong>
      );
    } else if (match[8] || match[9]) {
      nodes.push(
        <em
          key={`italic-${key++}`}
          className="italic"
        >
          {match[8] ?? match[9]}
        </em>
      );
    } else if (match[10]) {
      let url = match[10];

      const trailing = url.match(/[.,!?;:]+$/)?.[0] ?? "";
      url = url.slice(0, url.length - trailing.length);

      nodes.push(
        <a
          key={`url-${key++}`}
          href={url}
          target="_blank"
          rel="noopener noreferrer"
          title="เปิดเว็บไซต์"
          className="text-blue-400 underline underline-offset-2 break-all hover:text-blue-300"
        >
          {url}
          <span className="ml-1 text-xs">↗</span>
        </a>
      );

      pushText(trailing);
    }

    lastIndex = regex.lastIndex;
  }

  pushText(normalized.slice(lastIndex));

  return nodes;
}


// ==========================================
// Markdown Renderer
// ==========================================

function renderMarkdownText(text: string): ReactNode[] {
  const lines = text.replace(/\r\n/g, "\n").split("\n");

  const elements: ReactNode[] = [];

  let paragraph: string[] = [];
  let listItems: string[] = [];
  let listType: "ul" | "ol" | null = null;
  let quoteLines: string[] = [];
  let key = 0;

  const flushParagraph = () => {
    if (!paragraph.length) return;

    elements.push(
      <p
        key={`paragraph-${key++}`}
        className="my-1 whitespace-pre-wrap break-words leading-7"
      >
        {renderRichText(paragraph.join("\n"))}
      </p>
    );

    paragraph = [];
  };

  const flushList = () => {
    if (!listItems.length || !listType) return;

    const items = listItems;
    const ListTag = listType;

    elements.push(
      <ListTag
        key={`list-${key++}`}
        className={`${
          listType === "ul" ? "list-disc" : "list-decimal"
        } my-2 space-y-1 pl-6`}
      >
        {items.map((item, index) => (
          <li
            key={index}
            className="whitespace-pre-wrap break-words pl-1"
          >
            {renderRichText(item)}
          </li>
        ))}
      </ListTag>
    );

    listItems = [];
    listType = null;
  };

  const flushQuote = () => {
    if (!quoteLines.length) return;

    elements.push(
      <blockquote
        key={`quote-${key++}`}
        className="my-2 border-l-2 border-zinc-500 pl-3 text-zinc-300"
      >
        {renderRichText(quoteLines.join("\n"))}
      </blockquote>
    );

    quoteLines = [];
  };

  const flushAll = () => {
    flushParagraph();
    flushList();
    flushQuote();
  };

  for (const line of lines) {
    if (!line.trim()) {
      flushAll();
      continue;
    }

    const heading = line.match(/^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$/);

    if (heading) {
      flushAll();

      const level = heading[1].length;

      const sizeClass =
        level === 1
          ? "text-xl font-bold"
          : level === 2
            ? "text-lg font-bold"
            : level === 3
              ? "text-base font-semibold"
              : "text-sm font-semibold";

      elements.push(
        <div
          key={`heading-${key++}`}
          className={`${sizeClass} mb-1 mt-3 text-zinc-100`}
        >
          {renderRichText(heading[2])}
        </div>
      );

      continue;
    }

    if (/^\s{0,3}(?:---+|___+|\*\*\*+)\s*$/.test(line)) {
      flushAll();

      elements.push(
        <hr
          key={`hr-${key++}`}
          className="my-3 border-zinc-700"
        />
      );

      continue;
    }

    const quote = line.match(/^\s{0,3}>\s?(.*)$/);

    if (quote) {
      flushParagraph();
      flushList();
      quoteLines.push(quote[1]);
      continue;
    }

    flushQuote();

    const unordered = line.match(/^\s{0,3}[-\*+]\s+(.+)$/);
    const ordered = line.match(/^\s{0,3}\d+[.)]\s+(.+)$/);

    if (unordered || ordered) {
      flushParagraph();

      const nextType = unordered ? "ul" : "ol";

      if (listType && listType !== nextType) {
        flushList();
      }

      listType = nextType;
      listItems.push((unordered ?? ordered)![1]);

      continue;
    }

    flushList();
    paragraph.push(line);
  }

  flushAll();

  return elements;
}

// ==========================================
// Utility
// ==========================================

function clip(text: string) {
  return text.length > MAX_RESULT_CHARS
    ? text.slice(0, MAX_RESULT_CHARS) + "\n...[ตัดข้อความที่ยาวเกิน]"
    : text;
}

// ==========================================
// Build Run Result Message
// ==========================================

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

// ==========================================
// Code Block Component
// ==========================================

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
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          path: name.trim(),
          content: code,
          overwrite,
        }),
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
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          path: savedPath,
          approved: true,
        }),
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
    <div className="assistant-code-block my-2">
      <div className="assistant-code-header flex items-center justify-between px-3 py-2 text-xs">
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

      <pre className="assistant-code-content overflow-x-auto p-4">
        <code>{code}</code>
      </pre>

      {open && (
        <div className="border-t border-zinc-700 bg-zinc-900 p-3 text-sm">
          <p className="mb-2 text-zinc-300">
            บันทึกลง Workspace (โฟลเดอร์{" "}
            <code>thaimate\workspace</code> เท่านั้น)
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

          {status && (
            <p className="mt-2 text-zinc-300">{status}</p>
          )}

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
            {preview.execution_enabled
              ? "ตรวจสอบก่อนรัน"
              : "การรันโค้ดถูกปิดชั่วคราว"}
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

          <p className="mb-2 text-xs text-amber-200/80">
            {preview.warning ??
              "ระบบยังไม่อนุญาตให้รันโค้ดจนกว่าจะมี Isolated Sandbox"}
          </p>

          <div className="flex gap-2">
            {preview.execution_enabled && (
              <button
                onClick={approveRun}
                disabled={running}
                className="rounded bg-emerald-600 px-3 py-1.5 font-medium hover:bg-emerald-500 disabled:opacity-60"
              >
                อนุมัติและรัน
              </button>
            )}

            <button
              onClick={() => setPreview(null)}
              className="rounded bg-zinc-800 px-3 py-1.5 hover:bg-zinc-700"
            >
              ปิด
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
            <p className="mb-2 text-xs text-zinc-500">
              (ไม่มี output)
            </p>
          )}

          {savedPath && (
            <button
              onClick={() =>
                onSendResult(buildResultMessage(savedPath, result))
              }
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

// ==========================================
// Assistant Content
// ==========================================

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
          <div
            key={i}
            className="assistant-prose min-w-0 break-words"
          >
            {renderMarkdownText(p.text)}
          </div>
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

// ==========================================
// Main Application
// ==========================================

export default function Home() {
  const [messages, setMessages] = useState<Message[]>([
    { role: "assistant", content: GREETING },
  ]);

  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [convId, setConvId] = useState<number | null>(null);
  const [files, setFiles] = useState<string[]>([]);
  const [knowledgeSources, setKnowledgeSources] = useState<KnowledgeSource[]>([]);
  const [attached, setAttached] = useState<string | null>(null);
  const [selectedImages, setSelectedImages] = useState<ChatImage[]>([]);
  const [imageStatus, setImageStatus] = useState("");
  const [uploading, setUploading] = useState(false);
  const [fileStatus, setFileStatus] = useState("");
  const [attachmentExpanded, setAttachmentExpanded] = useState(false);
  const [modelProvider, setModelProvider] = useState<ModelProvider>("ollama");
  const [geminiAvailable, setGeminiAvailable] = useState(false);
  const [deletingConversationId, setDeletingConversationId] = useState<number | null>(null);
  const [deletingAll, setDeletingAll] = useState(false);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const imageInputRef = useRef<HTMLInputElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const sendingRef = useRef(false);

  // ป้องกันคำขอโหลดประวัติแชตเก่าเขียนทับข้อความใหม่
  const conversationLoadTokenRef = useRef(0);

  async function addImageFiles(fileList: FileList | null) {
    if (!fileList?.length) return;

    const availableSlots = Math.max(0, 3 - selectedImages.length);
    if (availableSlots === 0) {
      setImageStatus("แนบภาพได้สูงสุด 3 ภาพต่อข้อความ");
      return;
    }

    const additions: ChatImage[] = [];

    for (const file of Array.from(fileList).slice(0, availableSlots)) {
      if (!["image/png", "image/jpeg", "image/webp"].includes(file.type)) {
        setImageStatus("รองรับเฉพาะภาพ PNG, JPG และ WEBP");
        continue;
      }
      if (file.size > 10 * 1024 * 1024) {
        setImageStatus(\`\${file.name}: ไฟล์ต้นฉบับใหญ่เกิน 10 MB\`);
        continue;
      }

      try {
        const bitmap = await createImageBitmap(file);
        const longestSide = Math.max(bitmap.width, bitmap.height);
        let blob: Blob = file;

        if (file.size > 4 * 1024 * 1024 || longestSide > 2200) {
          const scale = Math.min(1, 2000 / longestSide);
          const canvas = document.createElement("canvas");
          canvas.width = Math.max(1, Math.round(bitmap.width * scale));
          canvas.height = Math.max(1, Math.round(bitmap.height * scale));
          const context = canvas.getContext("2d");
          if (!context) throw new Error("ไม่สามารถประมวลผลรูปภาพได้");
          context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
          blob = await new Promise<Blob>((resolve, reject) => {
            canvas.toBlob(
              (value) => value ? resolve(value) : reject(new Error("แปลงรูปภาพไม่สำเร็จ")),
              "image/jpeg",
              0.9
            );
          });
        }
        bitmap.close();

        if (blob.size > 4 * 1024 * 1024) {
          throw new Error("รูปหลังปรับขนาดยังใหญ่เกิน 4 MB");
        }

        const dataUrl = await new Promise<string>((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => typeof reader.result === "string"
            ? resolve(reader.result)
            : reject(new Error("อ่านรูปภาพไม่สำเร็จ"));
          reader.onerror = () => reject(new Error("อ่านรูปภาพไม่สำเร็จ"));
          reader.readAsDataURL(blob);
        });

        const encoded = dataUrl.split(",")[1];
        if (!encoded) throw new Error("ข้อมูลรูปภาพไม่ถูกต้อง");

        const mime = blob.type as ChatImage["mime_type"];
        additions.push({
          mime_type: mime,
          data: encoded,
          name: file.name.slice(0, 160),
        });
      } catch (error) {
        setImageStatus(error instanceof Error ? error.message : "เตรียมรูปภาพไม่สำเร็จ");
      }
    }

    if (additions.length) {
      setSelectedImages((current) => [...current, ...additions].slice(0, 3));
      setImageStatus(\`แนบรูปภาพแล้ว \${Math.min(3, selectedImages.length + additions.length)} / 3 ภาพ\`);
    }
  }

  // ========================================
  // Refresh Conversations
  // ========================================

  async function refreshConversations() {
    try {
      const res = await fetch(`${API}/conversations`);

      if (res.ok) {
        setConversations(await res.json());
      }
    } catch {
      console.error("Failed to load conversations");
    }
  }

  async function refreshModels() {
    try {
      const res = await fetch(`${API}/models`);
      if (!res.ok) return;
      const data = await res.json();
      const gemini = Array.isArray(data.models)
        ? data.models.find((item: { id?: string }) => item.id === "gemini")
        : null;
      setGeminiAvailable(Boolean(gemini?.available));
    } catch {
      setGeminiAvailable(false);
      console.error("Failed to load model availability");
    }
  }

  // ========================================
  // Refresh Workspace Files
  // ========================================

  async function refreshFiles() {
    try {
      const res = await fetch(`${API}/files`);

      if (res.ok) {
        const data: string[] = await res.json();

        const supported =
          /\.(pdf|docx|txt|csv|xlsx|md|py|js|ts|tsx|jsx|html|css|json)$/i;

        setFiles(data.filter((path) => supported.test(path)));
      }
    } catch {
      console.error("Failed to load workspace files");
    }
  }

  async function refreshKnowledgeSources() {
    try {
      const res = await fetch(`${API}/knowledge/sources`);

      if (res.ok) {
        setKnowledgeSources(await res.json());
      }
    } catch {
      console.error("Failed to load indexed knowledge sources");
    }
  }

  // ========================================
  // Upload File
  // ========================================

  async function uploadFile(file: File, overwrite = false) {
    setUploading(true);

    setFileStatus(
      overwrite
        ? "กำลังแทนที่ไฟล์และสร้างดัชนีใหม่..."
        : "กำลังอัปโหลดและอ่านเอกสาร..."
    );

    try {
      const form = new FormData();
      form.append("file", file);

      const endpoint = `${API}/files/upload${
        overwrite ? "?overwrite=true" : ""
      }`;

      const res = await fetch(endpoint, {
        method: "POST",
        body: form,
      });

      const data = await res.json();

      if (res.status === 409 && !overwrite) {
        const confirmed = window.confirm(
          `มีไฟล์ชื่อ ${file.name} อยู่แล้ว ต้องการแทนที่ไฟล์เดิมและสร้างข้อมูลความรู้ใหม่หรือไม่?`
        );

        if (confirmed) {
          await uploadFile(file, true);
          return;
        }

        setFileStatus("ยกเลิกการแทนที่ไฟล์เดิมแล้ว");
        return;
      }

      if (!res.ok) {
        throw new Error(
          data.detail ?? `อัปโหลดไม่สำเร็จ (HTTP ${res.status})`
        );
      }

      setAttached(data.source);
      setAttachmentExpanded(true);

      await Promise.all([
        refreshFiles(),
        refreshKnowledgeSources(),
      ]);

      setFileStatus(
        `เพิ่ม ${data.filename} สำเร็จ และจัดทำดัชนีแล้ว ${data.chunks} ส่วน`
      );
    } catch (error) {
      setFileStatus(
        error instanceof Error
          ? error.message
          : "อัปโหลดไฟล์ไม่สำเร็จ"
      );
    } finally {
      setUploading(false);

      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
    }
  }

  // ========================================
  // Delete Attached File
  // ========================================

  async function deleteAttachedFile() {
    if (!attached || !attached.startsWith("uploads/")) return;

    const confirmed = window.confirm(
      `ยืนยันลบไฟล์ ${attached} และข้อมูลความรู้ที่จัดทำไว้หรือไม่?`
    );

    if (!confirmed) return;

    setUploading(true);
    setFileStatus("กำลังลบไฟล์และข้อมูลความรู้...");

    try {
      const res = await fetch(
        `${API}/files?path=${encodeURIComponent(attached)}`,
        {
          method: "DELETE",
        }
      );

      const data = await res.json();

      if (!res.ok) {
        throw new Error(data.detail ?? "ลบไฟล์ไม่สำเร็จ");
      }

      setAttached(null);

      await Promise.all([
        refreshFiles(),
        refreshKnowledgeSources(),
      ]);

      setFileStatus(
        `ลบไฟล์แล้ว และลบข้อมูล RAG ${data.deleted_chunks} ส่วน`
      );
    } catch (error) {
      setFileStatus(
        error instanceof Error
          ? error.message
          : "ลบไฟล์ไม่สำเร็จ"
      );
    } finally {
      setUploading(false);
    }
  }

  // ========================================
  // Open Conversation
  // ========================================

  async function openConversation(id: number) {
    const requestToken = ++conversationLoadTokenRef.current;

    try {
      const res = await fetch(`${API}/conversations/${id}/messages`);

      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }

      const data: Message[] = await res.json();

      // ป้องกันประวัติเก่ากลับมาเขียนทับข้อความใหม่
      if (
        requestToken !== conversationLoadTokenRef.current ||
        sendingRef.current
      ) {
        console.info(
          "[ThaiMate] Ignored stale conversation load:",
          id
        );

        return;
      }

      const previousFileMessage = [...data]
        .reverse()
        .find(
          (message) =>
            message.role === "user" &&
            message.content.includes("[เอกสารอ้างอิง: ")
        );

      const previousFileMatch =
        previousFileMessage?.content.match(
          /\[เอกสารอ้างอิง: ([^\]]+)\]/
        );

      setAttached(previousFileMatch?.[1] ?? null);
      setAttachmentExpanded(false);

      setMessages([
        { role: "assistant", content: GREETING },
        ...data,
      ]);

      setConvId(id);
      const selectedConversation = conversations.find((item) => item.id === id);
      if (selectedConversation?.model_provider) {
        setModelProvider(selectedConversation.model_provider);
      }

      try {
        localStorage.setItem(
          "thaimate_conv_id",
          String(id)
        );
      } catch {}
    } catch (error) {
      if (
        requestToken !== conversationLoadTokenRef.current ||
        sendingRef.current
      ) {
        return;
      }

      console.error("Failed to load conversation:", error);

      alert(
        "โหลดประวัติแชตไม่สำเร็จ กรุณาตรวจสอบ Backend"
      );
    }
  }

  // ========================================
  // New Conversation
  // ========================================

  function newChat() {
    conversationLoadTokenRef.current += 1;

    setMessages([
      { role: "assistant", content: GREETING },
    ]);

    setConvId(null);
    setAttached(null);
    setAttachmentExpanded(false);
    setFileStatus("");

    try {
      localStorage.removeItem("thaimate_conv_id");
    } catch {}
  }

  useEffect(() => {
    if (!convId) return;
    const activeConversation = conversations.find((item) => item.id === convId);
    if (activeConversation?.model_provider) {
      setModelProvider(activeConversation.model_provider);
    }
  }, [convId, conversations]);

  // ========================================
  // Delete Conversation History
  // ========================================

  function resetDeletedActiveConversation() {
    conversationLoadTokenRef.current += 1;
    setMessages([{ role: "assistant", content: GREETING }]);
    setConvId(null);
    setAttached(null);
    setAttachmentExpanded(false);
    setFileStatus("");
    try {
      localStorage.removeItem("thaimate_conv_id");
    } catch {}
  }

  async function deleteConversation(id: number) {
    if (loading || deletingConversationId !== null || deletingAll) return;
    const target = conversations.find((item) => item.id === id);
    const confirmed = window.confirm(
      `ยืนยันลบบทสนทนา${target?.title ? ` “${target.title}”` : "นี้"}?\nข้อความทั้งหมดในบทสนทนานี้จะถูกลบด้วย`
    );
    if (!confirmed) return;

    setDeletingConversationId(id);
    try {
      const res = await fetch(`${API}/conversations/${id}`, { method: "DELETE" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail ?? "ลบประวัติแชตไม่สำเร็จ");
      setConversations((current) => current.filter((item) => item.id !== id));
      if (convId === id) resetDeletedActiveConversation();
    } catch (error) {
      window.alert(error instanceof Error ? error.message : "ลบประวัติแชตไม่สำเร็จ");
    } finally {
      setDeletingConversationId(null);
    }
  }

  async function deleteAllConversations() {
    if (loading || deletingAll || deletingConversationId !== null || conversations.length === 0) return;
    const confirmed = window.confirm(
      `ยืนยันลบประวัติแชตทั้งหมด ${conversations.length} รายการ?\nการลบนี้ไม่สามารถย้อนกลับได้\nไฟล์ Workspace และ Knowledge Base จะไม่ถูกลบ`
    );
    if (!confirmed) return;

    setDeletingAll(true);
    try {
      const res = await fetch(`${API}/conversations`, { method: "DELETE" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail ?? "ลบประวัติแชตทั้งหมดไม่สำเร็จ");
      setConversations([]);
      resetDeletedActiveConversation();
    } catch (error) {
      window.alert(error instanceof Error ? error.message : "ลบประวัติแชตทั้งหมดไม่สำเร็จ");
    } finally {
      setDeletingAll(false);
    }
  }

  // ========================================
  // Initial Loading
  // ========================================

  useEffect(() => {
    refreshConversations();
    refreshModels();
    refreshFiles();
    refreshKnowledgeSources();

    try {
      const saved = localStorage.getItem("thaimate_conv_id");

      if (saved) {
        const savedId = Number(saved);

        if (Number.isFinite(savedId) && savedId > 0) {
          void openConversation(savedId);
        }
      }
    } catch (error) {
      console.error(
        "Failed to restore conversation:",
        error
      );
    }

    // ยกเลิกคำขอโหลดประวัติที่ยังไม่เสร็จเมื่อ Component ถูกถอดออก
    return () => {
      conversationLoadTokenRef.current += 1;
    };

    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ========================================
  // Auto Scroll
  // ========================================

  useEffect(() => {
    bottomRef.current?.scrollIntoView({
      behavior: "smooth",
    });
  }, [messages]);

  // ========================================
  // Send Message
  // ========================================

  async function handleSend(override?: string) {
  const fromButton = override !== undefined;
  const typedText = (fromButton ? override : input).trim();
  const messageImages = fromButton ? [] : selectedImages;
  const text = typedText || (
    messageImages.length
      ? "ช่วยวิเคราะห์รูปภาพที่แนบมา อธิบายสิ่งที่เห็นและประเด็นสำคัญ"
      : ""
  );

  if ((!text && !messageImages.length) || loading || sendingRef.current) return;

  if (modelProvider === "gemini" && messageImages.length) {
    window.alert("การวิเคราะห์รูปภาพขณะนี้รองรับ Qwen Local ผ่าน Ollama เท่านั้น กรุณาเลือก Qwen Local");
    return;
  }

  // Require explicit consent before sending data to Gemini Cloud.
  const cloudConsent =
    modelProvider === "gemini"
      ? window.confirm(
          "คำเตือน: การใช้ Gemini จะส่งข้อมูลออกจากเครื่องไปยังบริการ Cloud ของ Google\n\n" +
          "ข้อมูลที่อาจถูกส่งประกอบด้วย:\n" +
          "- ข้อความที่คุณกำลังส่ง\n" +
          "- ประวัติการสนทนาที่แนบไปกับคำขอ\n" +
          "- เนื้อหาเอกสารและข้อมูลจาก Knowledge Base ที่เกี่ยวข้อง\n" +
          "- ไฟล์ PDF ต้นฉบับ ในกรณีสรุป PDF ด้วย Gemini\n\n" +
          "ข้อมูลเหล่านี้จะถูกประมวลผลผ่านบริการภายนอก ไม่ได้อยู่ภายในเครื่องของคุณเท่านั้น\n\n" +
          "คุณยินยอมให้ส่งข้อมูลเพื่อดำเนินการต่อหรือไม่?"
        )
      : false;

  if (modelProvider === "gemini" && !cloudConsent) {
    return;
  }

  sendingRef.current = true;

    // ยกเลิกสิทธิ์คำขอโหลดประวัติเก่าทันทีที่เริ่มส่ง
    conversationLoadTokenRef.current += 1;

    let content = text;
    let knowledgeSource: string | null = null;

    // ========================================
    // ตรวจสอบและจัดทำดัชนีไฟล์
    // ========================================

    if (!fromButton && attached) {
      knowledgeSource = attached;

      const isIndexed = knowledgeSources.some(
        (item) => item.source === attached
      );

      if (!isIndexed) {
        try {
          const indexResponse = await fetch(
            `${API}/knowledge/index`,
            {
              method: "POST",
              headers: {
                "Content-Type": "application/json",
              },
              body: JSON.stringify({
                path: attached,
              }),
            }
          );

          const indexData = await indexResponse.json();

          if (!indexResponse.ok) {
            throw new Error(
              indexData.detail ?? "จัดทำดัชนีไฟล์ไม่สำเร็จ"
            );
          }

          await refreshKnowledgeSources();
        } catch (error) {
          setMessages((prev) => [
            ...prev,
            {
              role: "assistant",
              content:
                error instanceof Error
                  ? `⚠️ ${error.message}`
                  : "⚠️ อ่านและจัดทำดัชนีไฟล์ไม่สำเร็จ",
            },
          ]);

          sendingRef.current = false;
          return;
        }
      }

      content = `${text}\n\n[เอกสารอ้างอิง: ${attached}]`;
    }

    // ========================================
    // เตรียมประวัติการสนทนา
    // ========================================

    const history: Message[] = [
      ...messages.slice(1),
      {
        role: "user",
        content,
        ...(messageImages.length ? { images: messageImages } : {}),
      },
    ];

    if (!fromButton) {
      setInput("");
      setSelectedImages([]);
      setImageStatus("");
    }

    setLoading(true);

    // แสดงข้อความผู้ใช้และช่องรอคำตอบ
    setMessages((prev) => [
      ...prev,
      { role: "user", content },
      { role: "assistant", content: "" },
    ]);

    // ========================================
    // เตรียมตัวสะสม Stream
    // ========================================

    let receivedText = "";

    const updateAssistantMessage = (nextContent: string) => {
      setMessages((prev) => {
        const copy = [...prev];
        const lastIndex = copy.length - 1;

        if (
          lastIndex >= 0 &&
          copy[lastIndex].role === "assistant"
        ) {
          copy[lastIndex] = {
            ...copy[lastIndex],
            content: nextContent,
          };
        } else {
          copy.push({
            role: "assistant",
            content: nextContent,
          });
        }

        return copy;
      });
    };

    // ========================================
    // Request Backend
    // ========================================

    try {
      const res = await fetch(`${API}/chat/stream`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          messages: history,
          conversation_id: convId,
          knowledge_source: knowledgeSource,
          model_provider: modelProvider,
          cloud_consent: cloudConsent,
        }),
      });

      console.info("[ThaiMate] Response:", {
        status: res.status,
        contentType: res.headers.get("content-type"),
      });

      if (!res.ok) {
        const detail = await res.text().catch(() => "");

        throw new Error(
          detail
            ? `Backend Error ${res.status}: ${detail.slice(0, 300)}`
            : `Backend Error ${res.status}`
        );
      }

      if (!res.body) {
        throw new Error(
          "Backend ไม่ได้ส่งข้อมูลกลับมา"
        );
      }

      // ========================================
      // รับ Conversation ID
      // ========================================

      const idHeader = res.headers.get(
        "X-Conversation-Id"
      );

      if (idHeader) {
        const id = Number(idHeader);

        setConvId(id);

        try {
          localStorage.setItem(
            "thaimate_conv_id",
            String(id)
          );
        } catch (error) {
          console.warn(
            "[ThaiMate] Cannot save conversation ID:",
            error
          );
        }
      }

      // ========================================
      // อ่านข้อมูล Stream
      // ========================================

      const reader = res.body.getReader();
      const decoder = new TextDecoder("utf-8");

      try {
        while (true) {
          const { done, value } = await reader.read();

          if (done) break;

          if (value && value.length > 0) {
            const chunk = decoder.decode(value, {
              stream: true,
            });

            if (chunk) {
              receivedText += chunk;

              // อัปเดต UI ด้วยข้อความที่สะสมทั้งหมด
              updateAssistantMessage(receivedText);
            }
          }
        }
      } finally {
        reader.releaseLock();
      }

      // อ่านข้อมูลที่เหลืออยู่ใน Decoder
      const remaining = decoder.decode();

      if (remaining) {
        receivedText += remaining;
        updateAssistantMessage(receivedText);
      }

      console.info("[ThaiMate] Stream completed:", {
        characters: receivedText.length,
        isEmpty: !receivedText.trim(),
      });

      if (!receivedText.trim()) {
        throw new Error(
          "Backend เชื่อมต่อสำเร็จ แต่ไม่ได้ส่งข้อความตอบกลับ (Stream ว่าง)"
        );
      }
    } catch (error) {
      console.error(
        "[ThaiMate] Chat request failed:",
        error
      );

      const errorMessage =
        error instanceof Error
          ? error.message
          : "เกิดข้อผิดพลาดที่ไม่ทราบสาเหตุ";

      setMessages((prev) => {
        const copy = [...prev];
        const lastIndex = copy.length - 1;

        const warning = `⚠️ ${errorMessage}`;

        if (
          lastIndex >= 0 &&
          copy[lastIndex].role === "assistant"
        ) {
          const currentContent = copy[lastIndex].content;

          copy[lastIndex] = {
            ...copy[lastIndex],
            content: currentContent
              ? `${currentContent}\n\n${warning}`
              : warning,
          };
        } else {
          copy.push({
            role: "assistant",
            content: warning,
          });
        }

        return copy;
      });
    } finally {
      sendingRef.current = false;
      setLoading(false);

      refreshConversations();
    }
  }

  // ========================================
  // User Interface
  // ========================================

  return (
    <div className="app-shell flex h-dvh min-h-[540px] text-zinc-100">
      {/* Sidebar */}

      <aside className="sidebar-shell hidden w-[272px] shrink-0 flex-col md:flex">
        <div className="flex items-center gap-3 px-5 pb-7 pt-6">
          <div
            className="brand-mark"
            aria-hidden="true"
          >
            T
          </div>

          <div className="min-w-0">
            <p className="text-[15px] font-semibold tracking-[0.01em] text-slate-100">
              ThaiMate
            </p>

            <p className="mt-0.5 text-[11px] tracking-[0.12em] text-slate-500">
              PERSONAL AI
            </p>
          </div>
        </div>

        <div className="px-4">
          <button
            onClick={newChat}
            disabled={loading}
            className="new-chat-button flex w-full items-center justify-center gap-2 rounded-xl px-4 py-3 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-50"
          >
            <span className="text-lg leading-none">＋</span>
            <span>เริ่มแชตใหม่</span>
          </button>
        </div>

        <div className="mt-8 flex items-center justify-between px-5 pb-3">
          <p className="text-[11px] font-semibold tracking-[0.13em] text-slate-500">
            ประวัติการสนทนา
          </p>

          <div className="flex items-center gap-2">
            <span className="rounded-full bg-white/[0.05] px-2 py-0.5 text-[10px] tabular-nums text-slate-500">
              {conversations.length}
            </span>
            {conversations.length > 0 && (
              <button
                type="button"
                onClick={deleteAllConversations}
                disabled={loading || deletingAll || deletingConversationId !== null}
                title="ลบประวัติแชตทั้งหมด"
                className="rounded-md px-1.5 py-1 text-[10px] text-red-400/80 transition hover:bg-red-500/10 hover:text-red-300 disabled:opacity-40"
              >
                {deletingAll ? "กำลังลบ..." : "ลบทั้งหมด"}
              </button>
            )}
          </div>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-3 pb-4">
          {conversations.length === 0 && (
            <p className="rounded-lg px-3 py-4 text-xs leading-6 text-slate-600">
              บทสนทนาที่บันทึกไว้จะแสดงตรงนี้
            </p>
          )}

          {conversations.map((c) => (
            <div key={c.id} className="group mb-1 flex min-w-0 items-center gap-1">
              <button
                type="button"
                onClick={() => !loading && openConversation(c.id)}
                title={`${c.title} · ${c.model_provider === "gemini" ? "Gemini" : "Qwen Local"}`}
                className={`conversation-item flex min-w-0 flex-1 items-center gap-2 rounded-lg px-3 py-2.5 text-left text-[13px] ${
                  c.id === convId ? "conversation-item-active" : ""
                }`}
              >
                <span className="shrink-0 text-xs text-slate-500" aria-hidden="true">
                  {c.model_provider === "gemini" ? "☁" : "◷"}
                </span>
                <span className="min-w-0 flex-1 truncate">{c.title}</span>
              </button>
              <button
                type="button"
                onClick={() => deleteConversation(c.id)}
                disabled={loading || deletingAll || deletingConversationId !== null}
                title={`ลบแชต: ${c.title}`}
                aria-label={`ลบแชต ${c.title}`}
                className="shrink-0 rounded-md px-2 py-2 text-xs text-slate-600 opacity-100 transition hover:bg-red-500/10 hover:text-red-300 disabled:opacity-30 sm:opacity-0 sm:group-hover:opacity-100 sm:focus:opacity-100"
              >
                {deletingConversationId === c.id ? "…" : "✕"}
              </button>
            </div>
          ))}
        </div>

        <div className="sidebar-footer mx-4 mb-4 rounded-xl p-3.5">
          <div className="flex items-center gap-2">
            <span className="status-dot" />

            <span className="text-xs font-medium text-slate-300">
              Hybrid AI environment
            </span>
          </div>

          <p className="mt-2 text-[11px] leading-5 text-slate-500">
            เลือกใช้ AI บนเครื่องหรือ Cloud ได้ตามต้องการ
          </p>
        </div>
      </aside>

      {/* Main Chat */}

      <main className="flex min-w-0 min-h-0 flex-1 flex-col">
        <header className="main-header flex min-h-[76px] items-center justify-between px-5 sm:px-8">
          <div className="flex min-w-0 items-center gap-3">
            <div
              className="brand-mark brand-mark-small md:hidden"
              aria-hidden="true"
            >
              T
            </div>

            <div className="min-w-0">
              <h1 className="truncate text-[15px] font-semibold tracking-[0.01em] text-slate-100 sm:text-base">
                ThaiMate AI
              </h1>

              <p className="mt-0.5 text-xs text-slate-500">
                ผู้ช่วย AI ส่วนตัวของคุณ
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2 rounded-xl border border-white/[0.07] bg-white/[0.025] px-2 py-1.5 sm:px-3">
            <span className={`h-2 w-2 rounded-full ${modelProvider === "gemini" ? "bg-sky-400" : "status-dot"}`} />
            <label className="flex items-center gap-2 text-[11px] text-slate-400">
              <span className="hidden sm:inline">โมเดล</span>
              <select
                value={modelProvider}
                onChange={(event) => setModelProvider(event.target.value as ModelProvider)}
                disabled={loading || uploading}
                aria-label="เลือกโมเดล AI"
                className="max-w-[150px] bg-transparent text-xs text-slate-200 outline-none disabled:opacity-50 sm:max-w-none"
              >
                <option value="ollama" className="bg-slate-900">Qwen 3.5 4B · Local</option>
                <option value="gemini" disabled={!geminiAvailable} className="bg-slate-900">
                  Gemini · {geminiAvailable ? "Cloud" : "ยังไม่ตั้งค่า API"}
                </option>
              </select>
            </label>
          </div>
        </header>

        {/* Messages */}

        <div className="chat-scroll min-h-0 flex-1 overflow-y-auto px-4 py-7 sm:px-7 sm:py-9">
          <div className="mx-auto flex w-full max-w-3xl flex-col gap-7">
            {messages.map((m, i) => {
              const isLast = i === messages.length - 1;
              const streaming = loading && isLast;

              if (m.role === "user") {
                return (
                  <div
                    key={i}
                    className="flex justify-end"
                  >
                    <div className="user-message max-h-[32rem] max-w-[88%] overflow-auto rounded-2xl px-4 py-3 text-[14px] leading-7 sm:max-w-[80%]">
                      {m.images?.length ? (
                        <div className="mb-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
                          {m.images.map((image, imageIndex) => (
                            <img
                              key={`${i}-${imageIndex}`}
                              src={imageSource(image)}
                              alt={image.name || "ภาพแนบ"}
                              className="max-h-64 max-w-full rounded-lg object-contain"
                            />
                          ))}
                        </div>
                      ) : null}
                      <p className="whitespace-pre-wrap break-words">{m.content}</p>
                    </div>
                  </div>
                );
              }

              return (
                <div
                  key={i}
                  className="assistant-message-row flex items-start gap-3 sm:gap-4"
                >
                  <div
                    className="assistant-avatar mt-0.5 shrink-0"
                    aria-hidden="true"
                  >
                    T
                  </div>

                  <div className="assistant-message min-w-0 flex-1 pt-0.5 text-[14px] leading-7">
                    {m.content ? (
                      <AssistantContent
                        content={m.content}
                        canAct={!loading}
                        onSaved={refreshFiles}
                        onSendResult={(t) => handleSend(t)}
                      />
                    ) : streaming ? (
                      <div className="typing-state flex items-center gap-2.5 py-1.5">
                        <span className="text-xs text-slate-500">
                          ThaiMate กำลังคิด
                        </span>

                        <span
                          className="typing-dots"
                          aria-label="กำลังประมวลผล"
                        >
                          <i />
                          <i />
                          <i />
                        </span>
                      </div>
                    ) : null}
                  </div>
                </div>
              );
            })}

            <div ref={bottomRef} />
          </div>
        </div>

        {/* Composer */}

        <div className="composer-area px-4 pb-5 pt-3 sm:px-7 sm:pb-7">
          <div className="mx-auto w-full max-w-3xl">
            <AssistantTools
              disabled={loading || uploading}
              onUsePrompt={(prompt) => {
                setInput(prompt);
                void handleSend(prompt);
              }}
            />

            {/* Compact File Upload and Image Attachments */}

            <section className="attachment-panel mb-2 rounded-xl p-2.5">
              <input
                ref={fileInputRef}
                type="file"
                accept=".pdf,.docx,.txt,.csv,.xlsx,.md,.py,.js,.ts,.tsx,.jsx,.html,.css,.json"
                className="hidden"
                onChange={(event) => {
                  const file = event.target.files?.[0];

                  if (file) {
                    setAttachmentExpanded(true);
                    uploadFile(file);
                  }
                }}
              />

              <input
                ref={imageInputRef}
                type="file"
                accept="image/png,image/jpeg,image/webp"
                multiple
                className="hidden"
                onChange={(event) => {
                  void addImageFiles(event.target.files);
                  event.target.value = "";
                }}
              />

              {/* Compact Toolbar */}

              <div className="flex min-w-0 items-center gap-2">
                <span
                  className="attachment-icon shrink-0"
                  aria-hidden="true"
                >
                  ⌁
                </span>

                <select
                  value={attached ?? ""}
                  onFocus={() => {
                    refreshFiles();
                    refreshKnowledgeSources();
                  }}
                  onChange={(event) =>
                    setAttached(event.target.value || null)
                  }
                  disabled={loading || uploading}
                  aria-label="เลือกไฟล์จาก Workspace"
                  className="workspace-select h-10 min-w-0 flex-1 rounded-lg px-3 text-xs outline-none disabled:opacity-50"
                >
                  <option value="">
                    เลือกไฟล์จาก Workspace...
                  </option>

                  {files.map((file) => (
                    <option key={file} value={file}>
                      {file}
                      {knowledgeSources.some(
                        (item) => item.source === file
                      )
                        ? " ✓"
                        : " · ยังไม่ทำดัชนี"}
                    </option>
                  ))}
                </select>

                <button
                  type="button"
                  onClick={() => fileInputRef.current?.click()}
                  disabled={loading || uploading}
                  title="อัปโหลดเอกสาร"
                  className="upload-button inline-flex h-10 shrink-0 items-center justify-center gap-1.5 rounded-lg px-3 text-xs font-medium disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <span className="text-base leading-none">
                    ＋
                  </span>

                  <span className="hidden sm:inline">
                    {uploading ? "กำลังอัปโหลด..." : "เพิ่มไฟล์"}
                  </span>

                  <span className="sm:hidden">เพิ่ม</span>
                </button>

                <button
                  type="button"
                  onClick={() => imageInputRef.current?.click()}
                  disabled={loading || uploading || selectedImages.length >= 3}
                  title="แนบรูปภาพเพื่อให้ Qwen วิเคราะห์"
                  className="quiet-button inline-flex h-10 shrink-0 items-center justify-center rounded-lg px-3 text-xs disabled:opacity-50"
                >
                  ＋ รูปภาพ
                </button>

                <button
                  type="button"
                  onClick={() =>
                    setAttachmentExpanded((prev) => !prev)
                  }
                  aria-expanded={attachmentExpanded}
                  aria-label={
                    attachmentExpanded
                      ? "ซ่อนรายละเอียดไฟล์"
                      : "แสดงรายละเอียดไฟล์"
                  }
                  title={
                    attachmentExpanded
                      ? "ซ่อนรายละเอียด"
                      : "จัดการไฟล์"
                  }
                  className="quiet-button inline-flex h-10 w-9 shrink-0 items-center justify-center rounded-lg text-sm"
                >
                  {attachmentExpanded ? "⌃" : "⌄"}
                </button>
              </div>

              {selectedImages.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-2">
                  {selectedImages.map((image, index) => (
                    <div key={`${image.name}-${index}`} className="relative h-20 w-20 overflow-hidden rounded-lg border border-white/10 bg-slate-900">
                      <img src={imageSource(image)} alt={image.name} className="h-full w-full object-cover" />
                      <button
                        type="button"
                        onClick={() => setSelectedImages((current) => current.filter((_, i) => i !== index))}
                        disabled={loading}
                        className="absolute right-1 top-1 rounded-full bg-black/75 px-1.5 text-xs text-white"
                        aria-label={`ลบภาพ ${image.name}`}
                      >
                        ×
                      </button>
                    </div>
                  ))}
                </div>
              )}

              {imageStatus && (
                <p className="mt-1 text-[10px] text-slate-400">{imageStatus}</p>
              )}

              {/* Selected File Status */}

              {attached && (
                <div className="mt-1.5 flex min-w-0 items-center gap-2 px-1">
                  <span className="status-dot shrink-0" />

                  <span className="min-w-0 truncate text-[10px] text-slate-400">
                    กำลังอ้างอิง {attached}
                  </span>
                </div>
              )}

              {/* Expanded Details */}

              {attachmentExpanded && (
                <div className="mt-2 space-y-2 border-t border-white/[0.06] pt-2.5">
                  {attached && (
                    <div className="flex flex-wrap items-center gap-2">
                      <button
                        type="button"
                        onClick={() => setAttached(null)}
                        disabled={loading || uploading}
                        className="quiet-button rounded-lg px-3 py-1.5 text-[11px] disabled:opacity-50"
                      >
                        ยกเลิกการเลือก
                      </button>

                      {attached.startsWith("uploads/") && (
                        <button
                          type="button"
                          onClick={deleteAttachedFile}
                          disabled={loading || uploading}
                          className="delete-button rounded-lg px-3 py-1.5 text-[11px] disabled:opacity-50"
                        >
                          ลบไฟล์
                        </button>
                      )}
                    </div>
                  )}

                  {fileStatus && (
                    <p className="whitespace-pre-wrap text-[11px] leading-5 text-slate-400">
                      {fileStatus}
                    </p>
                  )}

                  <p className="text-[10px] leading-5 text-slate-600">
                    รองรับ PDF, DOCX, TXT, CSV และ XLSX · ไฟล์ไม่เกิน 10 MB · ข้อความที่นำเข้า RAG ไม่เกิน 200 KB
                  </p>

                  <p className="text-[10px] text-slate-600">
                    WORKSPACE · ข้อมูลประกอบการสนทนา
                  </p>
                </div>
              )}

              {/* Compact Status Message */}

              {!attachmentExpanded && fileStatus && (
                <p className="mt-1 truncate px-1 text-[10px] text-slate-500">
                  {fileStatus}
                </p>
              )}
            </section>

            {/* Message Input */}

            <div className="message-composer flex items-center gap-2 rounded-2xl p-2">
              <input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) =>
                  e.key === "Enter" && handleSend()
                }
                placeholder={selectedImages.length ? "ถามเกี่ยวกับรูปภาพที่แนบ..." : "ส่งข้อความถึง ThaiMate..."}
                disabled={loading}
                aria-label="พิมพ์ข้อความ"
                className="message-input min-w-0 flex-1 bg-transparent px-3 py-2.5 text-sm outline-none disabled:opacity-50"
              />

              <button
                onClick={() => handleSend()}
                disabled={loading || (!input.trim() && selectedImages.length === 0)}
                aria-label="ส่งข้อความ"
                className="send-button inline-flex shrink-0 items-center justify-center gap-2 rounded-xl px-4 py-2.5 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-35"
              >
                <span>ส่ง</span>
                <span aria-hidden="true">↑</span>
              </button>
            </div>

            <p className="mt-2.5 text-center text-[10px] text-slate-600">
              ThaiMate อาจสร้างคำตอบที่ไม่ถูกต้องได้ · ตรวจสอบข้อมูลสำคัญก่อนนำไปใช้
            </p>
          </div>
        </div>
      </main>
    </div>
  );
}