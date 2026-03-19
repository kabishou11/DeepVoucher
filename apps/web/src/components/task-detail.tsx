"use client";

import Link from "next/link";
import { useEffect, useMemo, useState, useTransition } from "react";

type GenericRecord = Record<string, unknown>;

type TaskDetailPayload = {
  task: {
    task_id: string;
    status: string;
    attachment_count: number;
    created_at: string;
    updated_at: string;
    attachments: Array<{
      attachment_id: string;
      file_name: string;
      size: number;
    }>;
  };
  workflow: {
    mode?: string;
    voucher_date?: string;
    facts?: Array<Record<string, string | number>>;
    extractions?: GenericRecord[];
    packet_synthesis?: GenericRecord;
    amount_items?: Array<Record<string, string | string[]>>;
    posting_candidates?: GenericRecord[];
    preview_lines?: Array<Record<string, string | number>>;
    blockers?: Array<Record<string, string>>;
    review_actions?: Array<Record<string, string>>;
    nodes?: Array<Record<string, string>>;
    debug?: Record<string, unknown>;
  };
};

const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

type EditableLine = {
  row: number;
  zy: string;
  kmdm: string;
  kmmc: string;
};

function toStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => String(item));
}

function toRecordArray(value: unknown): GenericRecord[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is GenericRecord => typeof item === "object" && item !== null);
}

function toRecord(value: unknown): GenericRecord {
  return typeof value === "object" && value !== null ? (value as GenericRecord) : {};
}

function learnedCount(value: unknown): number {
  return toRecordArray(value).length;
}

function modeMeta(mode?: string) {
  if (mode === "modelscope_live") {
    return {
      label: "Live",
      detail: "真实多模态抽取、金额拆分、科目召回和规则校验均已跑通，可直接复核每一步依据。",
      tone: "node-success",
    };
  }
  if (mode === "live_error") {
    return {
      label: "Blocked",
      detail: "真实抽取失败时已直接阻断，不再回退示例数据，必须处理异常后才能继续。",
      tone: "node-blocked",
    };
  }
  return {
    label: "Mock",
    detail: "当前任务仍处于示例链路，适合验证界面与交互，不可视作真实结果。",
    tone: "node-warning",
  };
}

export function TaskDetail({ taskId }: { taskId: string }) {
  const [data, setData] = useState<TaskDetailPayload | null>(null);
  const [error, setError] = useState("");
  const [reviewLines, setReviewLines] = useState<EditableLine[]>([]);
  const [reviewVoucherDate, setReviewVoucherDate] = useState("");
  const [selectedAttachmentId, setSelectedAttachmentId] = useState("");
  const [exportPayload, setExportPayload] = useState<Record<string, unknown> | null>(null);
  const [statusMessage, setStatusMessage] = useState("可在下方修改摘要和科目，然后重新校验并导出。");
  const [isPending, startTransition] = useTransition();

  useEffect(() => {
    let ignore = false;
    fetch(`${apiBase}/api/tasks/${taskId}`)
      .then(async (res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((payload) => {
        if (!ignore) {
          setData(payload);
          setReviewVoucherDate(String(payload.workflow.voucher_date ?? ""));
          setSelectedAttachmentId(String(payload.task.attachments?.[0]?.attachment_id ?? ""));
          setReviewLines(
            (payload.workflow.preview_lines ?? []).map((line: Record<string, string | number>) => ({
              row: Number(line.row),
              zy: String(line.zy ?? ""),
              kmdm: String(line.kmdm ?? ""),
              kmmc: String(line.kmmc ?? ""),
            })),
          );
        }
      })
      .catch(() => {
        if (!ignore) setError("无法读取任务详情，请确认 API 已启动且任务存在。");
      });
    return () => {
      ignore = true;
    };
  }, [taskId]);

  const totalDebit = useMemo(() => {
    if (!data?.workflow.preview_lines) return "0.00";
    return data.workflow.preview_lines.reduce((sum, line) => sum + Number(line.jie ?? 0), 0).toFixed(2);
  }, [data]);

  const totalCredit = useMemo(() => {
    if (!data?.workflow.preview_lines) return "0.00";
    return data.workflow.preview_lines.reduce((sum, line) => sum + Number(line.dai ?? 0), 0).toFixed(2);
  }, [data]);

  const candidateMap = useMemo(() => {
    const map = new Map<number, GenericRecord[]>();
    data?.workflow.posting_candidates?.forEach((posting, index) => {
      map.set(index, toRecordArray(posting.account_candidates));
    });
    return map;
  }, [data]);
  const postingTraceMap = useMemo(() => {
    const map = new Map<number, GenericRecord>();
    data?.workflow.posting_candidates?.forEach((posting, index) => {
      map.set(index, toRecord(posting.selection_trace));
    });
    return map;
  }, [data]);
  const attachmentNameMap = useMemo(() => {
    const map = new Map<string, string>();
    data?.task.attachments.forEach((attachment) => {
      map.set(String(attachment.attachment_id), String(attachment.file_name));
    });
    return map;
  }, [data]);
  const attachmentUrlMap = useMemo(() => {
    const map = new Map<string, string>();
    data?.task.attachments.forEach((attachment) => {
      map.set(
        String(attachment.attachment_id),
        `${apiBase}/api/tasks/${taskId}/attachments/${String(attachment.attachment_id)}`,
      );
    });
    return map;
  }, [data, taskId]);
  const selectedAttachment = useMemo(
    () => data?.task.attachments.find((attachment) => attachment.attachment_id === selectedAttachmentId) ?? null,
    [data, selectedAttachmentId],
  );

  const debug = toRecord(data?.workflow.debug);
  const packetReviewNotes = toStringArray(debug.packet_review_notes);
  const dateHints = toRecordArray(debug.date_hints);
  const ruleTrace = toRecord(debug.rule_trace);
  const mode = modeMeta(data?.workflow.mode);

  function updateLine(row: number, patch: Partial<EditableLine>) {
    setReviewLines((prev) => prev.map((line) => (line.row === row ? { ...line, ...patch } : line)));
  }

  async function saveReview() {
    setStatusMessage("正在保存人工确认并重新校验...");
    const response = await fetch(`${apiBase}/api/tasks/${taskId}/review`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ lines: reviewLines, voucher_date: reviewVoucherDate }),
    });
    if (!response.ok) {
      setStatusMessage("保存失败，请检查 API 日志。");
      return;
    }
    const payload = await response.json();
    setData(payload);
    setReviewVoucherDate(String(payload.workflow.voucher_date ?? ""));
    setStatusMessage(payload.workflow.blockers?.length ? "已保存，但仍有阻断项。" : "已保存，当前可导出 JSON。");
  }

  async function exportVoucher() {
    setStatusMessage("正在导出最终 JSON...");
    const response = await fetch(`${apiBase}/api/tasks/${taskId}/export`, {
      method: "POST",
    });
    if (!response.ok) {
      setStatusMessage("当前仍有阻断项，暂不可导出。");
      return;
    }
    const payload = await response.json();
    setExportPayload(payload.payload);
    setStatusMessage("JSON 导出成功。");
  }

  if (error) {
    return (
      <div className="task-page">
        <Link href="/" className="back-link">
          返回工作台
        </Link>
        <article className="panel empty-state">{error}</article>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="task-page">
        <Link href="/" className="back-link">
          返回工作台
        </Link>
        <article className="panel empty-state">正在读取任务详情...</article>
      </div>
    );
  }

  return (
    <main className="task-page">
      <Link href="/" className="back-link">
        返回工作台
      </Link>

      <section className="hero detail-hero">
        <p className="eyebrow">Task Detail</p>
        <h1>{data.task.task_id}</h1>
        <p className="lede">{mode.detail}</p>
        <div className="hero-grid signal-grid compact-grid">
          <article className="stat-card">
            <span>任务状态</span>
            <strong>{data.task.status}</strong>
          </article>
          <article className="stat-card">
            <span>工作流模式</span>
            <strong>{mode.label}</strong>
          </article>
          <article className="stat-card">
            <span>最终凭证日期</span>
            <strong>{data.workflow.voucher_date ?? "-"}</strong>
          </article>
        </div>
      </section>

      {(data.workflow.blockers?.length ?? 0) > 0 ? (
        <section className="panel blocker-banner">
          <div className="panel-head">
            <p>当前阻断</p>
            <span>{data.workflow.blockers?.length ?? 0} Blockers</span>
          </div>
          <div className="chip-grid">
            {data.workflow.blockers?.map((item) => (
              <span className="candidate-chip blocker-chip" key={String(item.blocker_id)}>
                {String(item.blocker_type)}
              </span>
            ))}
          </div>
        </section>
      ) : null}

      <section className="workspace-grid">
        <article className="panel compact">
          <div className="panel-head">
            <p>任务概览</p>
            <span>{data.task.status}</span>
          </div>
          <ul className="mini-list">
            <li>附件数量：{data.task.attachment_count}</li>
            <li>凭证日期：{data.workflow.voucher_date ?? "-"}</li>
            <li>工作流模式：{data.workflow.mode ?? "-"}</li>
            <li>阻断项：{data.workflow.blockers?.length ?? 0}</li>
            <li>最后更新：{data.task.updated_at}</li>
          </ul>
        </article>
        <article className="panel compact tone-panel">
          <div className="panel-head">
            <p>凭证预览</p>
            <span>
              借 {totalDebit} / 贷 {totalCredit}
            </span>
          </div>
          <div className="voucher-preview">
            {data.workflow.preview_lines?.map((line) => (
              <div className="voucher-row" key={`${line.row}-${line.zy}`}>
                <div>
                  <strong>{String(line.zy)}</strong>
                  <p>{String(line.kmmc)}</p>
                </div>
                <div className="amount-pair">
                  <span>借 {String(line.jie)}</span>
                  <span>贷 {String(line.dai)}</span>
                </div>
              </div>
            ))}
          </div>
        </article>
      </section>

      <section className="panel-grid dashboard-grid">
        <article className="panel">
          <div className="panel-head">
            <p>过程判定</p>
            <span>{ruleTrace.name ? "Rule Visible" : "Trace Visible"}</span>
          </div>
          <div className="trace-stack">
            <div className="trace-card emphasis-card">
              <div>
                <strong>最终凭证日期</strong>
                <p>系统优先采用精确日期，再规范到月末日期；模糊日期区间不会抢占付款日期。</p>
              </div>
              <span className="node-status node-success">{data.workflow.voucher_date ?? "-"}</span>
            </div>
            {dateHints.length > 0 ? (
              <div className="hint-grid">
                {dateHints.map((hint, index) => (
                  <div className="hint-card" key={`${String(hint.source)}-${index}`}>
                    <strong>{String(hint.source ?? "unknown")}</strong>
                    <p>原始：{String(hint.raw ?? "-")}</p>
                    <p>规范：{String(hint.normalized ?? "-")}</p>
                    <span className={`node-status ${hint.is_exact ? "node-success" : "node-warning"}`}>
                      {hint.is_exact ? "exact" : "fuzzy"}
                    </span>
                  </div>
                ))}
              </div>
            ) : null}
            {ruleTrace.name ? (
              <div className="trace-card">
                <div>
                  <strong>当前样本命中规则</strong>
                  <p>{String(ruleTrace.name)}</p>
                </div>
                <div className="chip-grid">
                  <span className="candidate-chip">公厕 {String(ruleTrace.public_toilet_total ?? "-")}</span>
                  <span className="candidate-chip">环境 {String(ruleTrace.environment_total ?? "-")}</span>
                  {toStringArray(ruleTrace.public_toilet_items).slice(0, 5).map((item) => (
                    <span className="candidate-chip" key={item}>
                      {item}
                    </span>
                  ))}
                </div>
              </div>
            ) : null}
            {packetReviewNotes.length > 0 ? (
              <div className="trace-card">
                <div>
                  <strong>组单备注</strong>
                  <p>以下说明来自组单与规则修正阶段，用于解释为什么拆成当前这张凭证。</p>
                </div>
                <ul className="mini-list">
                  {packetReviewNotes.map((note) => (
                    <li key={note}>{note}</li>
                  ))}
                </ul>
              </div>
            ) : null}
          </div>
        </article>
        <article className="panel">
          <div className="panel-head">
            <p>流程节点</p>
            <span>{data.workflow.nodes?.length ?? 0} Nodes</span>
          </div>
          <div className="task-list">
            {data.workflow.nodes?.map((node) => (
              <div className="node-card" key={String(node.id)}>
                <div>
                  <strong>{String(node.label)}</strong>
                  <p>{String(node.summary)}</p>
                </div>
                <span className={`node-status node-${String(node.status)}`}>{String(node.status)}</span>
              </div>
            ))}
          </div>
        </article>
      </section>

      <section className="panel-grid dashboard-grid">
        <article className="panel">
          <div className="panel-head">
            <p>抽取结果</p>
            <span>{data.workflow.extractions?.length ?? 0} Attachments</span>
          </div>
          <div className="task-list">
            {data.workflow.extractions?.map((item) => {
              const totals = toRecordArray(item.totals).map((entry) => `${String(entry.label ?? "金额")} ${String(entry.amount ?? "-")}`);
              const lineItems = toRecordArray(item.line_items);
              return (
                <div className="node-card stretch-card" key={String(item.attachment_id)}>
                  <div>
                    <strong>{String(item.file_name)}</strong>
                    <p>{String(item.document_summary || item.document_type || "未识别摘要")}</p>
                    <p>日期提示：{String(item.voucher_date_hint || "-")}</p>
                    <p>明细条数：{lineItems.length}</p>
                    {totals.length > 0 ? <p>合计：{totals.join(" / ")}</p> : null}
                    <div className="candidate-row">
                      <button
                        className="candidate-chip"
                        onClick={() => setSelectedAttachmentId(String(item.attachment_id))}
                        type="button"
                      >
                        查看原图
                      </button>
                    </div>
                  </div>
                  <span className={`node-status ${data.workflow.mode === "modelscope_live" ? "node-success" : "node-warning"}`}>
                    {data.workflow.mode === "modelscope_live" ? "live" : "review"}
                  </span>
                </div>
              );
            })}
          </div>
        </article>
        <article className="panel evidence-panel">
          <div className="panel-head">
            <p>证据预览</p>
            <span>{selectedAttachment?.file_name ?? "No Selection"}</span>
          </div>
          <div className="evidence-preview-card">
            {selectedAttachment ? (
              <>
                <img
                  alt={selectedAttachment.file_name}
                  className="evidence-image"
                  src={attachmentUrlMap.get(selectedAttachment.attachment_id)}
                />
                <div className="evidence-preview-meta">
                  <strong>{selectedAttachment.file_name}</strong>
                  <p>{selectedAttachment.size} bytes</p>
                  <a
                    className="candidate-chip evidence-link"
                    href={attachmentUrlMap.get(selectedAttachment.attachment_id)}
                    rel="noreferrer"
                    target="_blank"
                  >
                    新窗口打开
                  </a>
                </div>
              </>
            ) : (
              <div className="empty-state">请选择一张证据附件查看原图。</div>
            )}
          </div>
          <div className="facts-grid">
            {data.task.attachments.map((attachment) => (
              <button
                className={`fact-card attachment-card-button ${selectedAttachmentId === attachment.attachment_id ? "attachment-card-active" : ""}`}
                key={attachment.attachment_id}
                onClick={() => setSelectedAttachmentId(attachment.attachment_id)}
                type="button"
              >
                <strong>{attachment.file_name}</strong>
                <p>{attachment.size} bytes</p>
              </button>
            ))}
          </div>
        </article>
      </section>

      <section className="panel-grid dashboard-grid">
        <article className="panel">
          <div className="panel-head">
            <p>附件与事实</p>
            <span>{data.workflow.facts?.length ?? 0} Facts</span>
          </div>
          <div className="facts-grid">
            {data.workflow.facts?.map((fact) => (
              <div className="fact-card" key={String(fact.fact_id)}>
                <strong>{String(fact.fact_type)}</strong>
                <p>{String(fact.normalized_value ?? fact.fact_value)}</p>
              </div>
            ))}
          </div>
        </article>
      </section>

      <section className="panel-grid dashboard-grid">
        <article className="panel">
          <div className="panel-head">
            <p>人工确认</p>
            <span>{reviewLines.length} Lines</span>
          </div>
          <div className="review-card review-date-card">
            <div className="review-head">
              <strong>凭证日期</strong>
              <span>{dateHints.length} 个候选</span>
            </div>
            <label className="review-field">
              <span>记账日期</span>
              <input value={reviewVoucherDate} onChange={(event) => setReviewVoucherDate(event.target.value)} />
            </label>
            {dateHints.length > 0 ? (
              <div className="candidate-row">
                {dateHints.map((hint, index) => (
                  <button
                    className="candidate-chip"
                    key={`${String(hint.source)}-${index}`}
                    onClick={() => setReviewVoucherDate(String(hint.normalized ?? ""))}
                    type="button"
                  >
                    {String(hint.source)} {String(hint.normalized ?? hint.raw ?? "")}
                  </button>
                ))}
              </div>
            ) : (
              <p className="warning-note">当前没有自动日期候选，请人工输入凭证日期。</p>
            )}
          </div>
          <div className="review-grid">
            {reviewLines.map((line) => {
              const candidates = candidateMap.get(line.row) ?? [];
              const postingTrace = postingTraceMap.get(line.row) ?? {};
              const evidenceNames =
                toStringArray(data.workflow.posting_candidates?.[line.row]?.evidence_ids).map(
                  (item) => attachmentNameMap.get(item) ?? item,
                ) ?? [];
              const evidenceIds = toStringArray(data.workflow.posting_candidates?.[line.row]?.evidence_ids);
              const learnedMatches = toRecordArray(postingTrace.learned_matches);
              const ruleMatches = toStringArray(postingTrace.rule_matches);
              return (
                <div className="review-card" key={line.row}>
                  <div className="review-head">
                    <strong>第 {line.row + 1} 行</strong>
                    <span>{candidates.length} 个候选</span>
                  </div>
                  <label className="review-field">
                    <span>摘要</span>
                    <input value={line.zy} onChange={(event) => updateLine(line.row, { zy: event.target.value })} />
                  </label>
                  <label className="review-field">
                    <span>科目代码</span>
                    <input value={line.kmdm} onChange={(event) => updateLine(line.row, { kmdm: event.target.value })} />
                  </label>
                  <label className="review-field">
                    <span>科目名称</span>
                    <input value={line.kmmc} onChange={(event) => updateLine(line.row, { kmmc: event.target.value })} />
                  </label>
                  <div className="review-meta">
                    <p>检索查询：{toStringArray(postingTrace.queries).join(" / ") || "-"}</p>
                    <p>证据附件：{evidenceNames.join(" / ") || "-"}</p>
                    <p>历史学习命中：{learnedMatches.length > 0 ? `${learnedMatches.length} 条` : "-"}</p>
                    <p>规则提示命中：{ruleMatches.join(" / ") || "-"}</p>
                  </div>
                  {learnedMatches.length > 0 ? (
                    <div className="learned-panel">
                      {learnedMatches.map((match) => (
                        <div className="learned-card" key={`${line.row}-${String(match.account_code)}`}>
                          <strong>
                            历史确认 {String(match.account_code)} {String(match.account_path ?? "")}
                          </strong>
                          <p>
                            匹配方式：{String(match.match_type ?? "-")} / 学习分数：{String(match.score ?? "-")}
                          </p>
                          <div className="chip-grid">
                            {toStringArray(match.matched_summaries).slice(0, 3).map((summary) => (
                              <span className="candidate-chip learned-chip" key={`${String(match.account_code)}-${summary}`}>
                                {summary}
                              </span>
                            ))}
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : null}
                  {evidenceIds.length > 0 ? (
                    <div className="candidate-row">
                      {evidenceIds.map((attachmentId) => (
                        <button
                          className="candidate-chip"
                          key={`${line.row}-${attachmentId}`}
                          onClick={() => setSelectedAttachmentId(attachmentId)}
                          type="button"
                        >
                          预览 {attachmentNameMap.get(attachmentId) ?? attachmentId}
                        </button>
                      ))}
                    </div>
                  ) : null}
                  {candidates.length > 0 ? (
                    <div className="candidate-detail-list">
                      {candidates.map((candidate) => (
                        <div className="candidate-detail-card" key={`${line.row}-${String(candidate.code)}`}>
                          <div className="candidate-detail-head">
                            <div>
                              <strong>
                                {String(candidate.code)} {String(candidate.path ?? candidate.name ?? "")}
                              </strong>
                              <p>分数：{String(candidate.score ?? "-")}</p>
                            </div>
                            <button
                              className="candidate-chip"
                              onClick={() =>
                                updateLine(line.row, {
                                  kmdm: String(candidate.code ?? ""),
                                  kmmc: String(candidate.path ?? candidate.name ?? ""),
                                })
                              }
                              type="button"
                            >
                              一键采用
                            </button>
                          </div>
                          <p className="candidate-detail-copy">
                            命中查询：{toStringArray(candidate.query_hits).join(" / ") || "-"}
                          </p>
                          {learnedCount(candidate.learned_hits) > 0 ? (
                            <p className="candidate-detail-copy">
                              历史学习：{learnedCount(candidate.learned_hits)} 条已确认样本支持该科目
                            </p>
                          ) : null}
                          {toStringArray(candidate.rule_hits).length > 0 ? (
                            <p className="candidate-detail-copy">
                              规则提示：{toStringArray(candidate.rule_hits).join(" / ")}
                            </p>
                          ) : null}
                          <div className="chip-grid">
                            {toStringArray(candidate.score_reasons).map((reason) => (
                              <span className="candidate-chip subtle-chip" key={`${String(candidate.code)}-${reason}`}>
                                {reason}
                              </span>
                            ))}
                            {toStringArray(candidate.rule_hits).map((hit) => (
                              <span className="candidate-chip rule-chip" key={`${String(candidate.code)}-rule-${hit}`}>
                                规则 {hit}
                              </span>
                            ))}
                            {toRecordArray(candidate.learned_hits).flatMap((match) =>
                              toStringArray(toRecord(match).matched_summaries).slice(0, 2).map((summary) => (
                                <span
                                  className="candidate-chip learned-chip"
                                  key={`${String(candidate.code)}-${String(toRecord(match).account_code ?? "")}-${summary}`}
                                >
                                  学习样本 {summary}
                                </span>
                              )),
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="warning-note">当前没有候选科目，请手工填入科目代码和名称。</p>
                  )}
                </div>
              );
            })}
          </div>
          <div className="action-row">
            <button className="action-button" onClick={() => startTransition(saveReview)} disabled={isPending}>
              保存并重校验
            </button>
            <button
              className="action-button secondary-button"
              onClick={() => startTransition(exportVoucher)}
              disabled={isPending || (data?.workflow.blockers?.length ?? 0) > 0}
            >
              导出 JSON
            </button>
            <p className="action-message">{statusMessage}</p>
          </div>
        </article>
        <article className="panel">
          <div className="panel-head">
            <p>金额单元</p>
            <span>{data.workflow.amount_items?.length ?? 0} Items</span>
          </div>
          <div className="task-list">
            {data.workflow.amount_items?.map((item) => (
              <div className="node-card" key={String(item.amount_item_id)}>
                <div>
                  <strong>{String(item.purpose)}</strong>
                  <p>方向：{String(item.direction_hint)}</p>
                  <p>证据数：{Array.isArray(item.evidence_ids) ? item.evidence_ids.length : 0}</p>
                </div>
                <span className="node-status node-success">{String(item.amount)}</span>
              </div>
            ))}
          </div>
        </article>
        <article className="panel">
          <div className="panel-head">
            <p>阻断与人工确认</p>
            <span>{data.workflow.blockers?.length ?? 0} Blockers</span>
          </div>
          <div className="task-list">
            {(data.workflow.blockers?.length ?? 0) === 0 ? (
              <div className="empty-state">当前没有阻断项，规则闸门已允许导出最终 JSON。</div>
            ) : (
              data.workflow.blockers?.map((item) => (
                <div className="node-card" key={String(item.blocker_id)}>
                  <div>
                    <strong>{String(item.blocker_type)}</strong>
                    <p>{String(item.message)}</p>
                  </div>
                  <span className="node-status node-blocked">blocked</span>
                </div>
              ))
            )}
          </div>
        </article>
      </section>

      <section className="panel-grid dashboard-grid">
        <article className="panel">
          <div className="panel-head">
            <p>调试备注</p>
            <span>Debug</span>
          </div>
          <pre className="debug-card">
            {JSON.stringify(
              {
                review_actions: data.workflow.review_actions,
                debug: data.workflow.debug,
              },
              null,
              2,
            )}
          </pre>
        </article>
        <article className="panel">
          <div className="panel-head">
            <p>最终 JSON</p>
            <span>{exportPayload ? "Ready" : "Pending"}</span>
          </div>
          <pre className="debug-card">{exportPayload ? JSON.stringify(exportPayload, null, 2) : "导出后会在这里显示最终凭证 JSON。"}</pre>
        </article>
      </section>
    </main>
  );
}
