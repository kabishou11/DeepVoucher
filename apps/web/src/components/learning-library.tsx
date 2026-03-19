"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

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
  amount_bucket?: string;
  exported_at: string;
  evidence_file_names?: string[];
  summary_keywords?: string[];
  evidence_keywords?: string[];
};

const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

export function LearningLibrary() {
  const [summary, setSummary] = useState<LearningSummary | null>(null);
  const [records, setRecords] = useState<LearningRecord[]>([]);
  const [query, setQuery] = useState("");
  const [direction, setDirection] = useState("all");
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([
      fetch(`${apiBase}/api/learning/summary`).then((res) => res.json()),
      fetch(`${apiBase}/api/learning/records?limit=200`).then((res) => res.json()),
    ])
      .then(([summaryPayload, recordsPayload]) => {
        setSummary(summaryPayload);
        setRecords(recordsPayload.items ?? []);
      })
      .catch(() => setError("无法读取学习库，请确认 API 已启动。"));
  }, []);

  const filteredRecords = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    return records.filter((record) => {
      const directionMatch = direction === "all" || record.direction === direction;
      const keywordMatch =
        !keyword ||
        `${record.summary} ${record.account_code} ${record.account_path}`.toLowerCase().includes(keyword);
      return directionMatch && keywordMatch;
    });
  }, [records, query, direction]);

  const groupedByAccount = useMemo(() => {
    const grouped = new Map<string, { code: string; path: string; count: number; lastExportedAt: string }>();
    filteredRecords.forEach((record) => {
      const key = record.account_code;
      const current = grouped.get(key);
      if (!current) {
        grouped.set(key, {
          code: record.account_code,
          path: record.account_path,
          count: 1,
          lastExportedAt: record.exported_at,
        });
        return;
      }
      current.count += 1;
      current.lastExportedAt = current.lastExportedAt > record.exported_at ? current.lastExportedAt : record.exported_at;
    });
    return Array.from(grouped.values()).sort((a, b) => b.count - a.count || b.lastExportedAt.localeCompare(a.lastExportedAt));
  }, [filteredRecords]);

  if (error) {
    return (
      <main className="task-page">
        <Link href="/" className="back-link">
          返回工作台
        </Link>
        <article className="panel empty-state">{error}</article>
      </main>
    );
  }

  return (
    <main className="task-page">
      <Link href="/" className="back-link">
        返回工作台
      </Link>

      <section className="hero detail-hero">
        <p className="eyebrow">Learning Library</p>
        <h1>学习记录库</h1>
        <p className="lede">
          这里只展示已经人工确认并成功导出的经验。系统只把这些经验作为召回与排序辅助，不会绕过阻断规则。
        </p>
        <div className="hero-grid signal-grid compact-grid">
          <article className="stat-card">
            <span>学习条目</span>
            <strong>{summary?.entry_count ?? 0}</strong>
          </article>
          <article className="stat-card">
            <span>覆盖科目</span>
            <strong>{summary?.account_count ?? 0}</strong>
          </article>
          <article className="stat-card">
            <span>最近学习</span>
            <strong>{summary?.last_exported_at ?? "-"}</strong>
          </article>
        </div>
      </section>

      <section className="panel-grid dashboard-grid">
        <article className="panel">
          <div className="panel-head">
            <p>筛选条件</p>
            <span>{filteredRecords.length} Records</span>
          </div>
          <div className="filter-grid">
            <label className="review-field">
              <span>关键词</span>
              <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="摘要 / 科目代码 / 科目路径" />
            </label>
            <label className="review-field">
              <span>方向</span>
              <select value={direction} onChange={(event) => setDirection(event.target.value)}>
                <option value="all">全部</option>
                <option value="debit">借方</option>
                <option value="credit">贷方</option>
              </select>
            </label>
          </div>
        </article>

        <article className="panel compact ledger-panel">
          <div className="panel-head">
            <p>学习边界</p>
            <span>Guard Rails</span>
          </div>
          <ul className="mini-list">
            <li>只学习已确认并成功导出的结果</li>
            <li>学习只影响候选排序，不自动通过校验</li>
            <li>金额区间与证据关键词仅作为辅助信号</li>
            <li>歧义场景仍然必须人工确认</li>
          </ul>
        </article>
      </section>

      <section className="panel-grid dashboard-grid">
        <article className="panel">
          <div className="panel-head">
            <p>按科目聚合</p>
            <span>{groupedByAccount.length} Accounts</span>
          </div>
          <div className="task-list">
            {groupedByAccount.length === 0 ? (
              <div className="empty-state">当前没有符合筛选条件的学习记录。</div>
            ) : (
              groupedByAccount.map((item) => (
                <div className="task-card" key={item.code}>
                  <div>
                    <strong>{item.code}</strong>
                    <p>{item.path}</p>
                  </div>
                  <div>
                    <span>{item.count} 条经验</span>
                    <p>{item.lastExportedAt}</p>
                  </div>
                </div>
              ))
            )}
          </div>
        </article>

        <article className="panel">
          <div className="panel-head">
            <p>最近学习明细</p>
            <span>{filteredRecords.length}</span>
          </div>
          <div className="candidate-detail-list">
            {filteredRecords.length === 0 ? (
              <div className="empty-state">没有匹配的学习记录。</div>
            ) : (
              filteredRecords.slice(0, 40).map((record) => (
                <div className="candidate-detail-card" key={`${record.task_id}-${record.account_code}-${record.summary}-${record.exported_at}`}>
                  <div className="candidate-detail-head">
                    <div>
                      <strong>{record.summary}</strong>
                      <p>
                        {record.account_code} {record.account_path}
                      </p>
                    </div>
                    <span className="node-status node-success">{record.direction}</span>
                  </div>
                  <p className="candidate-detail-copy">
                    金额：{record.amount} / 区间：{record.amount_bucket ?? "-"} / 任务：{record.task_id}
                  </p>
                  <div className="chip-grid">
                    {(record.summary_keywords ?? []).slice(0, 4).map((keyword) => (
                      <span className="candidate-chip learned-chip" key={`${record.task_id}-summary-${keyword}`}>
                        摘要 {keyword}
                      </span>
                    ))}
                    {(record.evidence_keywords ?? []).slice(0, 4).map((keyword) => (
                      <span className="candidate-chip rule-chip" key={`${record.task_id}-evidence-${keyword}`}>
                        证据 {keyword}
                      </span>
                    ))}
                  </div>
                </div>
              ))
            )}
          </div>
        </article>
      </section>
    </main>
  );
}
