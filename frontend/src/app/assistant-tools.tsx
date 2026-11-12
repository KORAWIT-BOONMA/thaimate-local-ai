"use client";

import { useEffect, useState, type FormEvent } from "react";

type Props = {
  disabled?: boolean;
  onUsePrompt: (prompt: string) => void;
};

type UserProfile = {
  fullName: string;
  education: string;
  skills: string;
  projects: string;
  contact: string;
};

type TaskItem = {
  id: string;
  title: string;
  done: boolean;
};

type Tab = "email" | "profile" | "tasks";

const PROFILE_KEY = "thaimate_profile_v1";
const TASKS_KEY = "thaimate_tasks_v1";
const NOTES_KEY = "thaimate_notes_v1";

const EMPTY_PROFILE: UserProfile = {
  fullName: "",
  education: "",
  skills: "",
  projects: "",
  contact: "",
};

export default function AssistantTools({
  disabled = false,
  onUsePrompt,
}: Props) {
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState<Tab>("email");
  const [ready, setReady] = useState(false);

  const [profile, setProfile] = useState<UserProfile>(EMPTY_PROFILE);
  const [tasks, setTasks] = useState<TaskItem[]>([]);
  const [notes, setNotes] = useState("");
  const [taskInput, setTaskInput] = useState("");

  const [applicationType, setApplicationType] = useState<"internship" | "job">("internship");
  const [company, setCompany] = useState("");
  const [position, setPosition] = useState("");
  const [jobDescription, setJobDescription] = useState("");
  const [language, setLanguage] = useState<"th" | "en">("th");
  const [tone, setTone] = useState<"formal" | "friendly">("formal");

  useEffect(() => {
    try {
      const savedProfile = localStorage.getItem(PROFILE_KEY);
      const savedTasks = localStorage.getItem(TASKS_KEY);
      const savedNotes = localStorage.getItem(NOTES_KEY);

      if (savedProfile) {
        const parsed = JSON.parse(savedProfile);
        if (parsed && typeof parsed === "object") {
          setProfile({ ...EMPTY_PROFILE, ...parsed });
        }
      }

      if (savedTasks) {
        const parsed = JSON.parse(savedTasks);
        if (Array.isArray(parsed)) {
          setTasks(parsed.filter(
            (item): item is TaskItem =>
              item &&
              typeof item.id === "string" &&
              typeof item.title === "string" &&
              typeof item.done === "boolean"
          ));
        }
      }

      if (savedNotes) setNotes(savedNotes);
    } catch (error) {
      console.warn("[ThaiMate] Could not restore personal tools:", error);
    } finally {
      setReady(true);
    }
  }, []);

  useEffect(() => {
    if (!ready) return;
    try {
      localStorage.setItem(PROFILE_KEY, JSON.stringify(profile));
      localStorage.setItem(TASKS_KEY, JSON.stringify(tasks));
      localStorage.setItem(NOTES_KEY, notes);
    } catch (error) {
      console.warn("[ThaiMate] Could not save personal tools:", error);
    }
  }, [ready, profile, tasks, notes]);

  function updateProfile<K extends keyof UserProfile>(
    key: K,
    value: UserProfile[K]
  ) {
    setProfile((current) => ({ ...current, [key]: value }));
  }

  function addTask(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const title = taskInput.trim();
    if (!title) return;

    setTasks((current) => [
      { id: `${Date.now()}-${current.length}`, title, done: false },
      ...current,
    ]);
    setTaskInput("");
  }

  function buildEmailPrompt(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (!position.trim() || !jobDescription.trim()) {
      window.alert("กรุณาระบุตำแหน่งและรายละเอียดประกาศงานก่อนครับ");
      return;
    }

    const profileLines = [
      profile.fullName && `ชื่อผู้สมัคร: ${profile.fullName}`,
      profile.education && `การศึกษา: ${profile.education}`,
      profile.skills && `ทักษะ: ${profile.skills}`,
      profile.projects && `โปรเจกต์/ผลงาน: ${profile.projects}`,
      profile.contact && `ข้อมูลติดต่อ/ลายเซ็น: ${profile.contact}`,
    ].filter(Boolean);

    const prompt = [
      `ช่วยร่างอีเมลสมัคร${applicationType === "internship" ? "ฝึกงาน" : "งาน"} โดยใช้ข้อมูลต่อไปนี้`,
      "",
      "ข้อมูลผู้สมัคร:",
      profileLines.length ? profileLines.join("\n") : "- ยังไม่มีข้อมูลโปรไฟล์ที่บันทึกไว้",
      "",
      `บริษัท: ${company.trim() || "ไม่ได้ระบุ"}`,
      `ตำแหน่ง: ${position.trim()}`,
      `ภาษา: ${language === "th" ? "ภาษาไทย" : "ภาษาอังกฤษ"}`,
      `โทนภาษา: ${tone === "formal" ? "สุภาพและเป็นทางการ" : "สุภาพ เป็นมิตร และเป็นธรรมชาติ"}`,
      "",
      "รายละเอียดประกาศงาน:",
      jobDescription.trim(),
      "",
      "ข้อกำหนด:",
      "- สร้าง Subject และ Body แยกจากกันให้ชัดเจน",
      "- เขียนให้เหมาะกับการสมัครงานหรือฝึกงานจริง",
      "- เชื่อมโยงทักษะและโปรเจกต์ของผู้สมัครกับตำแหน่งอย่างเป็นธรรมชาติ",
      "- ห้ามแต่งประสบการณ์ ทักษะ วุฒิการศึกษา หรือข้อมูลส่วนตัวที่ไม่ได้ให้ไว้",
      "- หากข้อมูลสำคัญขาดหาย ให้ใช้ข้อความที่เป็นกลางหรือแจ้งว่าควรเติมข้อมูลตรงไหน",
      "- ไม่ต้องส่งอีเมลจริง ให้สร้างฉบับร่างเพื่อให้ผู้ใช้ตรวจสอบและคัดลอก",
    ].join("\n");

    onUsePrompt(prompt);
    setOpen(false);
  }

  function planTasks() {
    const pending = tasks.filter((task) => !task.done);
    if (!pending.length && !notes.trim()) {
      window.alert("ยังไม่มีงานค้างหรือบันทึกย่อให้ช่วยจัดการครับ");
      return;
    }

    const prompt = [
      "ช่วยจัดลำดับและวางแผนงานประจำวันจากข้อมูลต่อไปนี้",
      "",
      "รายการงานที่ยังไม่เสร็จ:",
      pending.length
        ? pending.map((task, index) => `${index + 1}. ${task.title}`).join("\n")
        : "- ไม่มี",
      "",
      "บันทึกเพิ่มเติม:",
      notes.trim() || "- ไม่มี",
      "",
      "ช่วยจัดลำดับตามความเร่งด่วนและความสำคัญ แนะนำขั้นตอนเริ่มต้น และแยกสิ่งที่ต้องทำวันนี้กับสิ่งที่เลื่อนได้ โดยห้ามสร้างกำหนดส่งขึ้นมาเอง",
    ].join("\n");

    onUsePrompt(prompt);
    setOpen(false);
  }

  const tabClass = (value: Tab) =>
    `rounded-lg px-3 py-2 text-xs font-medium transition ${tab === value
      ? "bg-sky-500/15 text-sky-300"
      : "text-slate-400 hover:bg-white/[0.05] hover:text-slate-200"}`;

  return (
    <section className="mb-3">
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => { setTab("email"); setOpen(true); }}
          disabled={disabled}
          className="rounded-lg border border-sky-400/20 bg-sky-400/[0.07] px-3 py-2 text-xs font-medium text-sky-200 hover:bg-sky-400/[0.13] disabled:opacity-50"
        >
          ✉ ผู้ช่วยร่างอีเมล
        </button>
        <button
          type="button"
          onClick={() => { setTab("profile"); setOpen(true); }}
          disabled={disabled}
          className="rounded-lg border border-white/[0.08] bg-white/[0.03] px-3 py-2 text-xs text-slate-300 hover:bg-white/[0.07] disabled:opacity-50"
        >
          ◉ ข้อมูลส่วนตัว
        </button>
        <button
          type="button"
          onClick={() => { setTab("tasks"); setOpen(true); }}
          disabled={disabled}
          className="rounded-lg border border-white/[0.08] bg-white/[0.03] px-3 py-2 text-xs text-slate-300 hover:bg-white/[0.07] disabled:opacity-50"
        >
          ✓ งานและบันทึก
        </button>
        {open && (
          <button
            type="button"
            onClick={() => setOpen(false)}
            className="ml-auto rounded-lg px-2 py-2 text-xs text-slate-500 hover:text-slate-200"
            aria-label="ปิดเครื่องมือ"
          >
            ปิด ✕
          </button>
        )}
      </div>

      {open && (
        <div className="mt-2 rounded-xl border border-white/[0.08] bg-slate-950/70 p-3 sm:p-4">
          <div className="mb-3 flex flex-wrap gap-1 border-b border-white/[0.07] pb-3">
            <button type="button" className={tabClass("email")} onClick={() => setTab("email")}>ร่างอีเมล</button>
            <button type="button" className={tabClass("profile")} onClick={() => setTab("profile")}>โปรไฟล์</button>
            <button type="button" className={tabClass("tasks")} onClick={() => setTab("tasks")}>งานประจำวัน</button>
          </div>

          {tab === "email" && (
            <form onSubmit={buildEmailPrompt} className="space-y-3">
              <p className="text-xs leading-5 text-slate-400">
                กรอกประกาศงานและข้อมูลผู้สมัคร ระบบจะส่งรายละเอียดให้ AI ช่วยสร้างฉบับร่างในแชต คุณตรวจทานและคัดลอกได้ก่อนนำไปใช้
              </p>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                <label className="space-y-1 text-xs text-slate-400">
                  ประเภทการสมัคร
                  <select value={applicationType} onChange={(event) => setApplicationType(event.target.value as "internship" | "job")} className="w-full rounded-lg border border-white/10 bg-slate-900 px-3 py-2.5 text-sm text-slate-100">
                    <option value="internship">สมัครฝึกงาน</option>
                    <option value="job">สมัครงาน</option>
                  </select>
                </label>
                <label className="space-y-1 text-xs text-slate-400">
                  บริษัท
                  <input value={company} onChange={(event) => setCompany(event.target.value)} placeholder="ชื่อบริษัท" className="w-full rounded-lg border border-white/10 bg-slate-900 px-3 py-2.5 text-sm text-slate-100" />
                </label>
                <label className="space-y-1 text-xs text-slate-400 sm:col-span-2">
                  ตำแหน่งที่สมัคร *
                  <input required value={position} onChange={(event) => setPosition(event.target.value)} placeholder="เช่น AI Engineer Intern" className="w-full rounded-lg border border-white/10 bg-slate-900 px-3 py-2.5 text-sm text-slate-100" />
                </label>
                <label className="space-y-1 text-xs text-slate-400">
                  ภาษา
                  <select value={language} onChange={(event) => setLanguage(event.target.value as "th" | "en")} className="w-full rounded-lg border border-white/10 bg-slate-900 px-3 py-2.5 text-sm text-slate-100">
                    <option value="th">ภาษาไทย</option>
                    <option value="en">ภาษาอังกฤษ</option>
                  </select>
                </label>
                <label className="space-y-1 text-xs text-slate-400">
                  โทนภาษา
                  <select value={tone} onChange={(event) => setTone(event.target.value as "formal" | "friendly")} className="w-full rounded-lg border border-white/10 bg-slate-900 px-3 py-2.5 text-sm text-slate-100">
                    <option value="formal">สุภาพและเป็นทางการ</option>
                    <option value="friendly">สุภาพและเป็นมิตร</option>
                  </select>
                </label>
              </div>
              <label className="block space-y-1 text-xs text-slate-400">
                รายละเอียดประกาศงาน *
                <textarea required rows={5} value={jobDescription} onChange={(event) => setJobDescription(event.target.value)} placeholder="วางรายละเอียดตำแหน่ง คุณสมบัติ และหน้าที่ที่รับผิดชอบ..." className="w-full resize-y rounded-lg border border-white/10 bg-slate-900 px-3 py-2.5 text-sm leading-6 text-slate-100" />
              </label>
              <button type="submit" disabled={disabled} className="rounded-lg bg-sky-500 px-4 py-2.5 text-xs font-semibold text-white hover:bg-sky-400 disabled:opacity-50">
                สร้างฉบับร่างในแชต
              </button>
            </form>
          )}

          {tab === "profile" && (
            <div className="space-y-3">
              <p className="text-xs leading-5 text-slate-400">
                ข้อมูลนี้บันทึกไว้ใน Local Storage ของเบราว์เซอร์เครื่องนี้ และจะถูกแนบไปกับคำขอเมื่อใช้ตัวช่วยร่างอีเมลเท่านั้น
              </p>
              {([
                ["fullName", "ชื่อ-นามสกุล", "ชื่อที่ต้องการให้ปรากฏในเอกสาร"],
                ["education", "การศึกษา", "สาขา มหาวิทยาลัย ชั้นปี"],
                ["skills", "ทักษะ", "เช่น Python, FastAPI, RAG, Machine Learning"],
                ["projects", "โปรเจกต์และผลงาน", "สรุปผลงานที่เกี่ยวข้อง"],
                ["contact", "ข้อมูลติดต่อ/ลายเซ็น", "อีเมล เบอร์โทร หรือข้อความลงท้าย (ใส่เท่าที่ต้องการ)"],
              ] as const).map(([key, label, placeholder]) => (
                <label key={key} className="block space-y-1 text-xs text-slate-400">
                  {label}
                  <textarea rows={key === "projects" || key === "skills" ? 3 : 2} value={profile[key]} onChange={(event) => updateProfile(key, event.target.value)} placeholder={placeholder} className="w-full resize-y rounded-lg border border-white/10 bg-slate-900 px-3 py-2.5 text-sm leading-6 text-slate-100" />
                </label>
              ))}
              <p className="text-[11px] text-emerald-300/80">บันทึกอัตโนมัติบนเบราว์เซอร์เครื่องนี้</p>
            </div>
          )}

          {tab === "tasks" && (
            <div className="space-y-3">
              <form onSubmit={addTask} className="flex gap-2">
                <input value={taskInput} onChange={(event) => setTaskInput(event.target.value)} placeholder="เพิ่มงานที่ต้องทำ..." className="min-w-0 flex-1 rounded-lg border border-white/10 bg-slate-900 px-3 py-2.5 text-sm text-slate-100" />
                <button type="submit" disabled={!taskInput.trim()} className="rounded-lg border border-white/10 px-3 py-2 text-xs text-slate-200 disabled:opacity-40">เพิ่มงาน</button>
              </form>
              <div className="max-h-48 space-y-2 overflow-y-auto">
                {tasks.length === 0 && <p className="text-xs text-slate-500">ยังไม่มีรายการงาน</p>}
                {tasks.map((task) => (
                  <div key={task.id} className="flex items-start gap-2 rounded-lg bg-white/[0.03] px-3 py-2">
                    <input type="checkbox" checked={task.done} onChange={(event) => setTasks((items) => items.map((item) => item.id === task.id ? { ...item, done: event.target.checked } : item))} className="mt-1 accent-sky-400" />
                    <span className={`min-w-0 flex-1 break-words text-sm ${task.done ? "text-slate-500 line-through" : "text-slate-200"}`}>{task.title}</span>
                    <button type="button" onClick={() => setTasks((items) => items.filter((item) => item.id !== task.id))} className="text-xs text-slate-500 hover:text-red-300" aria-label="ลบงาน">ลบ</button>
                  </div>
                ))}
              </div>
              <label className="block space-y-1 text-xs text-slate-400">
                บันทึกย่อ
                <textarea rows={4} value={notes} onChange={(event) => setNotes(event.target.value)} placeholder="จดไอเดียหรือสิ่งที่ต้องจำ..." className="w-full resize-y rounded-lg border border-white/10 bg-slate-900 px-3 py-2.5 text-sm leading-6 text-slate-100" />
              </label>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-[11px] text-slate-500">รายการงานและบันทึกเก็บในเบราว์เซอร์เครื่องนี้</span>
                <button type="button" onClick={planTasks} disabled={disabled} className="rounded-lg bg-sky-500 px-3 py-2 text-xs font-semibold text-white hover:bg-sky-400 disabled:opacity-50">ให้ ThaiMate ช่วยวางแผน</button>
              </div>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
