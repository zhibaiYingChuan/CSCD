/* C-S-C-D 部署与效果看板前端逻辑 */
(function () {
  "use strict";

  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => Array.from(document.querySelectorAll(sel));

  /* ===== 主题切换 ===== */
  function initTheme() {
    const saved = localStorage.getItem("cscd-theme") || "dark";
    document.documentElement.setAttribute("data-theme", saved);
    $("#theme-toggle").textContent = saved === "dark" ? "🌙 深色" : "☀️ 浅色";
  }
  $("#theme-toggle").addEventListener("click", () => {
    const cur = document.documentElement.getAttribute("data-theme");
    const next = cur === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    localStorage.setItem("cscd-theme", next);
    $("#theme-toggle").textContent = next === "dark" ? "🌙 深色" : "☀️ 浅色";
  });

  /* ===== 部署配置标签切换 ===== */
  $$(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      $$(".tab-btn").forEach((b) => b.classList.remove("active"));
      $$(".tab-pane").forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
      $("#tab-" + btn.dataset.tab).classList.add("active");
    });
  });

  /* ===== 一键复制 ===== */
  function toast(msg) {
    const t = $("#toast");
    t.textContent = msg;
    t.classList.remove("hidden");
    setTimeout(() => t.classList.add("hidden"), 1500);
  }
  $$(".copy-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const code = $("#" + btn.dataset.target).innerText;
      if (navigator.clipboard) {
        navigator.clipboard.writeText(code).then(() => toast("已复制到剪贴板"));
      } else {
        // 降级：创建临时 textarea
        const ta = document.createElement("textarea");
        ta.value = code;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        document.body.removeChild(ta);
        toast("已复制到剪贴板");
      }
    });
  });

  /* ===== 展示预设推理轨迹示例（真实模型输出） ===== */
  const TRACE_SAMPLE = `<DECOMPOSE>
- 原子1：积分获取模块（下单、签到、评价等触发）
- 原子2：积分消耗模块（兑换、抵扣、退款）
- 原子3：账期过期模块（有效期、过期策略）
- 原子4：流水仓储模块（记录、对账、审计）
- 原子5：风控防刷模块（检测、限流、黑名单）
</DECOMPOSE>

<CLASSIFY>
- 原子1：事实（获取场景明确）
- 原子2：事实（消耗场景明确）
- 原子3：假设（过期策略需业务规则）
- 原子4：事实（流水仓储必需）
- 原子5：事实（风控防刷必需）
</CLASSIFY>

<SELECT>
- 原子1（获取）
- 原子4（流水仓储）
- 原子5（风控防刷）
</SELECT>

<COMBINE>
最终结论：采用事件驱动架构，积分获取/消耗通过 MQ 事件触发；
流水仓储用 append-only 积分流水表；风控在入口层做分布式限流 + 规则引擎。
与假设碰撞：过期策略假设 → 用定时任务扫描过期积分；
集成假设 → 通过 API 网关对接订单服务。
子目标：① 设计流水表结构；② 定义防刷阈值；③ 确定过期规则。

<<<summary>>>
key_points: 事件驱动；流水表 append-only；入口层风控；定时任务过期；3 个子目标
need_review: 过期规则需业务确认；防刷阈值需压测
<<</summary>>>
</COMBINE>`;

  $("#trace-sample").textContent = TRACE_SAMPLE;

  /* ===== 服务状态检测 ===== */
  function checkService() {
    const badge = $("#service-badge");
    fetch("/api/status", { method: "GET" })
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((d) => {
        if (d.ready) {
          badge.className = "badge badge-ok";
          badge.textContent = `● 服务就绪 · ${d.model || "模型"}`
            .replace("● 服务就绪 · ", "● 服务就绪 · ");
        } else {
          badge.className = "badge badge-error";
          badge.textContent = "● 未配置端点（见部署配置）";
        }
      })
      .catch(() => {
        badge.className = "badge badge-error";
        badge.textContent = "● 后端未启动（python start_services.py --all）";
      });
  }

  /* ===== 初始化 ===== */
  initTheme();
  checkService();
  setInterval(checkService, 15000);  // 每 15s 轮询服务状态
})();
