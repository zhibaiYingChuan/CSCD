// C-S-C-D Reasoning · VS Code 扩展主逻辑
// 通过 HTTP 调用本地 C-S-C-D WebUI 后端 /api/reason 执行推理，
// 在输出面板展示精炼结论、四阶轨迹、认知控制审计与账本信息。

const vscode = require("vscode");

/** @param {vscode.ExtensionContext} context */
function activate(context) {
  const output = vscode.window.createOutputChannel("C-S-C-D");

  // 命令：运行推理
  // 注意：cscd.reasonApiUrl 应指向本机服务，勿配置到不可信外部地址
  const runReason = vscode.commands.registerCommand("cscd.runReason", async () => {
    const config = vscode.workspace.getConfiguration("cscd");
    const apiUrl = config.get("reasonApiUrl", "http://127.0.0.1:8000/api/reason");

    // 让用户在快速输入框中输入问题
    const question = await vscode.window.showInputBox({
      placeHolder: "输入你的任务（例如：设计带权限的 TODO 后端 API）",
      prompt: "C-S-C-D 结构化推理",
      ignoreFocusOut: true,
    });
    if (!question) return;

    // 进度提示
    await vscode.window.withProgress(
      { location: vscode.ProgressLocation.Notification, title: "C-S-C-D 推理中…" },
      async () => {
        try {
          const controller = new AbortController();
          const timeoutId = setTimeout(() => controller.abort(), 30000);
          const res = await fetch(apiUrl, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ question }),
            signal: controller.signal,
          });
          clearTimeout(timeoutId);
          const data = await res.json();
          if (!res.ok) {
            throw new Error(data.detail || `请求失败 (${res.status})`);
          }
          renderResult(output, data, question);
        } catch (e) {
          vscode.window.showErrorMessage(
            `C-S-C-D 推理失败：${e.message}\n请确认后端已启动 (uvicorn main:app --port 8000)`
          );
        }
      }
    );
  });

  // 命令：打开效果看板
  const openDashboard = vscode.commands.registerCommand("cscd.openDashboard", () => {
    const config = vscode.workspace.getConfiguration("cscd");
    const url = config.get("dashboardUrl", "http://127.0.0.1:8000");
    vscode.env.openExternal(vscode.Uri.parse(url));
  });

  context.subscriptions.push(runReason, openDashboard);
}

/** 在输出面板渲染结构化推理结果 */
function renderResult(output, d, question) {
  output.clear();
  output.appendLine("=".repeat(56));
  output.appendLine("C-S-C-D 推理结果");
  output.appendLine("=".repeat(56));
  output.appendLine(`问题: ${question}`);
  output.appendLine(`复杂度: ${d.complexity}  策略: ${d.strategy}  任务类型: ${d.task_type}`);
  output.appendLine(`轮次: ${d.rounds}/${d.planned_rounds}  marks_valid: ${d.marks_valid}`);
  output.appendLine(`缓存命中: ${d.cache_hits}  输出Token: ${d.total_completion_tokens}`);
  output.appendLine("-".repeat(56));
  output.appendLine("[最终结论]");
  output.appendLine(d.reason || "(无)");

  if (d.cognition && Object.keys(d.cognition).length) {
    output.appendLine("-".repeat(56));
    output.appendLine("[认知控制审计]");
    const c = d.cognition;
    output.appendLine(`  工作空间: ${(c.workspace || []).join(" | ")}`);
    output.appendLine(`  稠密轨: ${c.dense_track || "(无符号)"}`);
    output.appendLine(`  桥接概念: ${(c.bridged_concepts || []).join(" | ")}`);
    output.appendLine(`  元认知动作: ${c.metacognition || "(无)"}`);
    output.appendLine(`  首轮锚定: anchored=${c.anchored} round=${c.anchor_round}`);
  }

  if (d.ledger && d.ledger.task_id) {
    output.appendLine("-".repeat(56));
    output.appendLine(`[账本] task_id=${d.ledger.task_id} 条目=${d.ledger.count}`);
  }

  if (d.raw_reason) {
    output.appendLine("-".repeat(56));
    output.appendLine("[完整四阶轨迹（审计）]");
    output.appendLine(d.raw_reason);
  }
  output.show();
}

module.exports = { activate, renderResult };
