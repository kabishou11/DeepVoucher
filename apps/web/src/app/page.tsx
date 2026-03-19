import { WorkbenchShell } from "@/components/workbench-shell";

const stages = [
  {
    title: "材料接收",
    detail: "上传一组图片，完成去重、纠偏、清晰度检测与票据初判。",
  },
  {
    title: "事实抽取",
    detail: "调用 Qwen/Qwen3.5-35B-A3B 提取日期、金额、用途、对象等证据化事实。",
  },
  {
    title: "金额拆分",
    detail: "将单一业务事件拆成支持多借多贷的 AmountItem。",
  },
  {
    title: "科目匹配",
    detail: "通过 LanceDB + 末级科目规则匹配最终会计科目。",
  },
  {
    title: "规则放行",
    detail: "借贷平衡、制度一致、层级末级、字段完整后才允许导出。",
  },
];

const principles = [
  "正确答案仅用于测试验收，不进入推理链路",
  "有歧义时必须阻断并进入人工确认",
  "一组图片默认生成一张凭证，但支持多借多贷",
  "每条分录均可反查证据来源与制度依据",
];

export default function HomePage() {
  return (
    <main className="page-shell">
      <section className="hero">
        <p className="eyebrow">Voucher Intelligence Workbench</p>
        <h1>凭证自动录入工作台</h1>
        <p className="lede">
          面向农村集体经济组织会计场景的本地化工作台。主流程由 LangGraph 驱动，知识层使用
          LanceDB，最终导出符合接口要求的凭证 JSON。
        </p>

        <div className="hero-grid">
          <article className="stat-card">
            <span>主模型</span>
            <strong>Qwen/Qwen3.5-35B-A3B</strong>
          </article>
          <article className="stat-card">
            <span>向量模型</span>
            <strong>bge-m3 本地复用</strong>
          </article>
          <article className="stat-card">
            <span>主工作流</span>
            <strong>LangGraph + 强规则闸门</strong>
          </article>
        </div>
      </section>

      <section className="panel-grid">
        <article className="panel">
          <div className="panel-head">
            <p>流程主线</p>
            <span>5 Stages</span>
          </div>
          <div className="timeline">
            {stages.map((stage, index) => (
              <div className="timeline-item" key={stage.title}>
                <div className="timeline-index">{String(index + 1).padStart(2, "0")}</div>
                <div>
                  <h2>{stage.title}</h2>
                  <p>{stage.detail}</p>
                </div>
              </div>
            ))}
          </div>
        </article>

        <article className="panel accent-panel">
          <div className="panel-head">
            <p>放行原则</p>
            <span>100% 准确率策略</span>
          </div>
          <ul className="principles">
            {principles.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </article>
      </section>

      <section className="panel-grid">
        <article className="panel compact">
          <div className="panel-head">
            <p>当前骨架</p>
            <span>Live</span>
          </div>
          <ul className="mini-list">
            <li>FastAPI + Next.js 本地联调已跑通</li>
            <li>任务详情页可视化真实抽取与规则闸门</li>
            <li>Pydantic 核心 schema 与 JSON 导出已可用</li>
            <li>当前样本可稳定回归到期望凭证 JSON</li>
          </ul>
        </article>
        <article className="panel compact">
          <div className="panel-head">
            <p>架构图谱</p>
            <span>Docs</span>
          </div>
          <ul className="mini-list">
            <li>`docs/architecture/2026-03-19-voucher-auto-entry-architecture.md`</li>
            <li>包含整体架构图、处理流程图、阻断与人工确认闭环</li>
            <li>后续继续抽象通用多借多贷规则引擎</li>
            <li>后续在本机正常权限环境复验 LanceDB 向量写入</li>
          </ul>
        </article>
      </section>

      <WorkbenchShell />
    </main>
  );
}
