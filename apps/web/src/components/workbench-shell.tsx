"use client";

import Link from "next/link";
import { useEffect, useMemo, useState, useTransition } from "react";

type KnowledgeSummary = {
  parsed_ready: boolean;
  embedding_model_ready?: boolean;
  embedding_runtime_ready?: boolean;
  vector_search_ready?: boolean;
  manifest: {
    account_count?: number;
    institution_chunk_count?: number;
  };
  index_status?: {
    available?: boolean;
    error?: string;
    vector_ready?: boolean;
    vector_dimension?: number;
    embedding_backend?: string;
  };
  search_status?: {
    backend?: string;
    search_mode?: string;
  };
};

type ReadinessReport = {
  overall_status: string;
  blockers: string[];
  checks: Array<{
    key: string;
    label: string;
    ok: boolean;
    status: string;
    detail: string;
  }>;
};

type LearningSummary = {
  memory_path?: string;
  entry_count?: number;
  account_count?: number;
  last_exported_at?: string;
};

type LearningRecord = {
  task_id: string;
  summary: string;
  direction: string;
  account_code: string;
  account_path: string;
  amount: string;
  exported_at: string;
  match_factors?: string[];
};

type TaskSummary = {
  task_id: string;
  status: string;
  created_at: string;
  updated_at: string;
  attachment_count: number;
};

const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

export function WorkbenchShell() {
  const [knowledge, setKnowledge] = useState<KnowledgeSummary | null>(null);
  const [readiness, setReadiness] = useState<ReadinessReport | null>(null);
  const [learning, setLearning] = useState<LearningSummary | null>(null);
  const [learningRecords, setLearningRecords] = useState<LearningRecord[]>([]);
  const [tasks, setTasks] = useState<TaskSummary[]>([]);
  const [message, setMessage] = useState(
    "拖入或选择一组附件，系统会创建本地任务并进入真实多模态工作流；若存在歧义或失败，将直接阻断而不是放行。",
  );
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [isPending, startTransition] = useTransition();

  useEffect(() => {
    startTransition(async () => {
      const [readinessResp, knowledgeResp, learningResp, learningRecordsResp, tasksResp] = await Promise.all([
        fetch(`${apiBase}/api/readiness`).then((res) => res.json()),
        fetch(`${apiBase}/api/knowledge/summary`).then((res) => res.json()),
        fetch(`${apiBase}/api/learning/summary`).then((res) => res.json()),
        fetch(`${apiBase}/api/learning/records?limit=6`).then((res) => res.json()),
        fetch(`${apiBase}/api/tasks`).then((res) => res.json()),
      ]);
      setReadiness(readinessResp);
      setKnowledge(knowledgeResp);
      setLearning(learningResp);
      setLearningRecords(learningRecordsResp.items ?? []);
      setTasks(tasksResp.items ?? []);
    });
  }, []);

  const statusText = useMemo(() => {
    if (!knowledge) return "读取中";
    if (knowledge.index_status?.available && knowledge.index_status?.vector_ready) {
      return "LanceDB + bge-m3 已就绪";
    }
    if (knowledge.index_status?.available) return "LanceDB 已就绪";
    if (knowledge.parsed_ready) return "结构化知识已就绪，当前回退 JSON 搜索";
    return "尚未构建知识层";
  }, [knowledge]);

  async function handleUpload() {
    if (selectedFiles.length === 0) {
      setMessage("请先选择至少一张图片。");
      return;
    }
    const form = new FormData();
    selectedFiles.forEach((file) => form.append("files", file));
    setMessage("正在创建任务并触发真实工作流...");

    const response = await fetch(`${apiBase}/api/tasks`, {
      method: "POST",
      body: form,
    });
    if (!response.ok) {
      setMessage("任务创建失败，请检查 API 是否运行。");
      return;
    }
    const payload = await response.json();
    setTasks((prev) => [payload.task, ...prev]);
    setSelectedFiles([]);
    setMessage(`任务 ${payload.task.task_id} 已创建，可进入详情页查看完整处理过程。`);
  }

  return (
    <>
      <section className="workspace-grid">
        <article className="panel upload-panel">
          <div className="panel-head">
            <p>任务入口</p>
            <span>{statusText}</span>
          </div>
          <p className="supporting-copy">
            现在上传后会直接进入真实多模态链路：逐图抽取、组单、金额拆分、候选科目召回、规则闸门、人工确认与 JSON 导出，全程可视化。
          </p>
          <label className="upload-dropzone" htmlFor="task-upload">
            <span>上传图片组</span>
            <strong>{selectedFiles.length > 0 ? `已选 ${selectedFiles.length} 张` : "点击选择或替换附件"}</strong>
            <small>建议直接选择 `ai验证/附件` 内的图片，便于后续联调。</small>
          </label>
          <input
            id="task-upload"
            className="sr-only"
            type="file"
            accept="image/*"
            multiple
            onChange={(event) => setSelectedFiles(Array.from(event.target.files ?? []))}
          />
          <div className="selected-files">
            {selectedFiles.slice(0, 6).map((file) => (
              <span key={`${file.name}-${file.size}`}>{file.name}</span>
            ))}
          </div>
          <div className="action-row">
            <button className="action-button" onClick={handleUpload} disabled={isPending}>
              创建任务
            </button>
            <p className="action-message">{message}</p>
          </div>
        </article>

        <article className="panel compact tone-panel">
          <div className="panel-head">
            <p>知识层状态</p>
            <span>Local</span>
          </div>
          <ul className="mini-list">
            <li>科目条目：{knowledge?.manifest?.account_count ?? "-"}</li>
            <li>制度条文块：{knowledge?.manifest?.institution_chunk_count ?? "-"}</li>
            <li>
              向量索引：
              {knowledge?.index_status?.vector_ready
                ? `已启用${knowledge.index_status.vector_dimension ? ` / ${knowledge.index_status.vector_dimension} 维` : ""}`
                : knowledge?.index_status?.available
                  ? "仅 FTS"
                  : "当前环境回退 JSON 搜索"}
            </li>
            <li>Embedding 运行时：{knowledge?.embedding_runtime_ready ? "已安装" : "未安装"}</li>
            <li>最近检索：{knowledge?.search_status?.search_mode ?? "-"}</li>
          </ul>
          {knowledge?.index_status?.error ? (
            <p className="warning-note">当前环境的文件权限会阻止 LanceDB 写表，因此 API 已自动回退为结构化 JSON 检索。</p>
          ) : null}
        </article>
      </section>

      <section className="panel-grid dashboard-grid">
        <article className="panel">
          <div className="panel-head">
            <p>最近任务</p>
            <span>{tasks.length} Tasks</span>
          </div>
          <div className="task-list">
            {tasks.length === 0 ? (
              <div className="empty-state">还没有任务。先上传一组附件，系统会为你生成第一条工作流记录。</div>
            ) : (
              tasks.map((task) => (
                <Link className="task-card" href={`/tasks/${task.task_id}`} key={task.task_id}>
                  <div>
                    <strong>{task.task_id}</strong>
                    <p>{task.status}</p>
                  </div>
                  <div>
                    <span>{task.attachment_count} 张附件</span>
                    <p>{task.updated_at}</p>
                  </div>
                </Link>
              ))
            )}
          </div>
        </article>

        <article className="panel compact ledger-panel">
          <div className="panel-head">
            <p>当前批次输出</p>
            <span>Live Visible</span>
          </div>
          <ul className="mini-list">
            <li>真实 ModelScope 抽取 + 确定性规则修正</li>
            <li>任务详情页展示日期决策、规则命中、阻断原因</li>
            <li>真实抽取失败时直接阻断，不再回退 mock 放行</li>
            <li>当前样本回归已与期望 JSON 一致</li>
          </ul>
        </article>
      </section>

      <section className="panel-grid dashboard-grid">
        <article className="panel compact">
          <div className="panel-head">
            <p>学习记忆</p>
            <span>Confirmed Only</span>
          </div>
          <ul className="mini-list">
            <li>记忆条目：{learning?.entry_count ?? 0}</li>
            <li>已覆盖科目：{learning?.account_count ?? 0}</li>
            <li>最近学习：{learning?.last_exported_at ?? "-"}</li>
            <li>仅从已确认并成功导出的凭证中积累经验</li>
          </ul>
          <div className="action-row action-row-compact">
            <Link className="candidate-chip evidence-link" href="/learning">
              打开学习库
            </Link>
          </div>
        </article>
        <article className="panel compact tone-panel">
          <div className="panel-head">
            <p>学习放行边界</p>
            <span>Safe Guard</span>
          </div>
          <ul className="mini-list">
            <li>历史经验只影响候选排序，不会自动放行</li>
            <li>有歧义时仍然阻断，必须人工确认</li>
            <li>学习命中会在任务详情页显示为可追溯依据</li>
            <li>经验库保存在本地，不依赖外部服务</li>
          </ul>
        </article>
      </section>

      <section className="panel-grid dashboard-grid">
        <article className="panel compact">
          <div className="panel-head">
            <p>交付就绪度</p>
            <span>{readiness?.overall_status === "ready" ? "Ready" : "Needs Attention"}</span>
          </div>
          <ul className="mini-list">
            <li>通过检查：{readiness?.checks?.filter((item) => item.ok).length ?? 0}</li>
            <li>待处理项：{readiness?.blockers?.length ?? 0}</li>
            <li>向量召回：{knowledge?.vector_search_ready ? "已进入主链路" : "未完全就绪"}</li>
            <li>真实 Token：{readiness?.checks?.find((item) => item.key === "modelscope_api_key")?.ok ? "已配置" : "未配置"}</li>
          </ul>
        </article>
        <article className="panel compact tone-panel">
          <div className="panel-head">
            <p>待处理项</p>
            <span>Checklist</span>
          </div>
          <ul className="mini-list">
            {(readiness?.blockers?.length ?? 0) === 0 ? (
              <li>当前关键项已满足，可进入联调或验收。</li>
            ) : (
              readiness?.blockers?.slice(0, 4).map((blocker) => <li key={blocker}>{blocker}</li>)
            )}
          </ul>
        </article>
      </section>

      <section className="panel-grid dashboard-grid">
        <article className="panel">
          <div className="panel-head">
            <p>最近学习记录</p>
            <span>{learningRecords.length} Records</span>
          </div>
          <div className="task-list">
            {learningRecords.length === 0 ? (
              <div className="empty-state">当前还没有学习记录。导出几张已确认凭证后，这里会开始累积经验。</div>
            ) : (
              learningRecords.map((record) => (
                <div className="task-card" key={`${record.task_id}-${record.account_code}-${record.summary}`}>
                  <div>
                    <strong>{record.summary}</strong>
                    <p>
                      {record.account_code} {record.account_path}
                    </p>
                  </div>
                  <div>
                    <span>
                      {record.direction} / {record.amount}
                    </span>
                    <p>{record.exported_at}</p>
                  </div>
                </div>
              ))
            )}
          </div>
        </article>
        <article className="panel compact ledger-panel">
          <div className="panel-head">
            <p>学习使用方式</p>
            <span>3-Way Fusion</span>
          </div>
          <ul className="mini-list">
            <li>知识检索负责制度与科目路径召回</li>
            <li>历史学习负责复用已确认的摘要、金额、证据经验</li>
            <li>规则提示负责业务强先验召回</li>
            <li>三路只影响候选排序，最终仍受阻断规则约束</li>
          </ul>
        </article>
      </section>
    </>
  );
}
