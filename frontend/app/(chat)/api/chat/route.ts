import {
  createUIMessageStream,
  createUIMessageStreamResponse,
  generateId,
} from "ai";
import { auth } from "@clerk/nextjs/server";
import { buildSubtasksForTool } from "@/lib/ai/tools/agent-execution";
import { FISCAL_COMMAND_MAP } from "@/lib/ai/tools/fiscal-tools";
import {
  getChatById,
  saveChat,
  saveMessages,
  updateChatTitleById,
} from "@/lib/db/queries";
import { ChatbotError } from "@/lib/errors";
import { generateUUID } from "@/lib/utils";

export const maxDuration = 60;

// ─── Mock delay config ────────────────────────────────────────────────────────
// 5 000 ms total per tool. Tasks share the budget proportionally.
const TOOL_MOCK_DELAY_MS = 5000;

function generateAgentId(): string {
  return `agent-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
}

/**
 * API Chat - Fiscal Console (Mock)
 * Tools execute sequentially (concatenated). Each tool emits task-level
 * stream events so the sidebar can track per-task progress in real time.
 */
export async function POST(request: Request) {
  const body = await request.json();
  const {
    id,
    messages: initialMessages = [],
    message: singularMessage,
    isToolApprovalFlow,
    selectedVisibilityType,
    profileId,
  } = body;

  const visibility = selectedVisibilityType || "private";
  const uiMessages = singularMessage
    ? [singularMessage]
    : initialMessages || [];

  const { userId } = await auth();

  if (!userId) {
    return new ChatbotError("unauthorized:chat").toResponse();
  }

  try {
    const message = uiMessages.at(-1);
    if (!message) return new ChatbotError("bad_request:api").toResponse();

    // Persist initial message for chat history
    if (uiMessages.length === 1 && userId) {
      try {
        const existingChat = await getChatById({ id });
        if (!existingChat) {
          const rawText =
            typeof message.content === "string"
              ? message.content
              : message.parts?.find((p: any) => p.type === "text")?.text || "";
          const quickCuitMatch = rawText.match(/(\d{11})/);

          const now = new Date();
          const day = now.getDate().toString().padStart(2, "0");
          const month = (now.getMonth() + 1).toString().padStart(2, "0");
          const time = `${now.getHours().toString().padStart(2, "0")}:${now.getMinutes().toString().padStart(2, "0")}`;
          const timestamp = `${day}/${month} ${time}`;
          const title = quickCuitMatch
            ? `Informe ${quickCuitMatch[1]} — ${timestamp}`
            : `Consola Fiscal — ${timestamp}`;

          await saveChat({
            id,
            userId,
            title,
            visibility,
          });
        }

        await saveMessages({
          messages: [
            {
              id: generateUUID(),
              chatId: id,
              role: message.role,
              parts:
                message.parts ||
                (message.content
                  ? [{ type: "text", text: message.content }]
                  : []),
              attachments: message.attachments || [],
              createdAt: new Date(),
            },
          ],
        });
      } catch (e) {
        console.error("Historical persistence failed:", e);
      }
    }

    let userText = "";
    if (message.content && typeof message.content === "string") {
      userText = message.content.trim();
    } else if (message.parts) {
      userText = (
        message.parts
          ?.filter((p: any) => p.type === "text")
          .map((p: any) => String(p.text ?? ""))
          .join("") ?? ""
      ).trim();
    }

    const fiscalMatch = userText.match(
      /^(\d{11})\s+((?:\/[^/]+?)(?:\s+\/[^/]+?)*)?\s*$/i
    );
    const cuit = fiscalMatch ? fiscalMatch[1] : null;

    if (fiscalMatch && cuit) {
      console.log("FISCAL CONSOLE EXECUTION - CUIT:", cuit);

      const streamInstance = createUIMessageStream({
        originalMessages: isToolApprovalFlow ? uiMessages : undefined,
        execute: async ({ writer: dataStream }) => {
          const textPartId = generateId();
          dataStream.write({ type: "text-start", id: textPartId });

          const commandsSection = fiscalMatch[2] ?? "";
          let commandNames = (
            commandsSection.match(/\/([^/]+?)(?=\s*\/|$)/g) ?? []
          ).map((c: any) => c.slice(1).trim().toLowerCase());

          // Macro expansion for /todo
          if (commandNames.includes("todo")) {
            commandNames = [
              "consultaarca",
              "sistemaregistral",
              "misfacilidades",
              "deudavencimientos",
              "rentascordoba",
              "calendariovencimientosarca",
              "informefiscal",
              "enviarmail",
            ];
          }

          const LABEL_MAP: Record<string, string> = {
            consultaarca: "ConsultaArca",
            sistemaregistral: "SistemaRegistral",
            misfacilidades: "MisFacilidades",
            deudavencimientos: "DeudaVencimientos",
            rentascordoba: "RentasCordoba",
            calendariovencimientosarca: "CalendarioVencimientosArca",
            informefiscal: "📖 InformeFiscal",
            enviarmail: "EnviarMail",
          };

          const formatSummary = (cmd: string, data: any) => {
            switch (cmd) {
              case "consultaarca":
                return `**Denominación**: ${data.denominacion}\n- **Condición**: ${data.condicionFiscal}\n- **Impuestos**: ${data.obligaciones.map((o: any) => `${o.impuesto} (${o.estado})`).join(", ")}`;
              case "sistemaregistral":
                return `**Razón Social**: ${data.razonSocial}\n- **Actividad**: ${data.actividadPrincipal.descripcion}\n- **Domicilio**: ${data.domicilioFiscal.calle} ${data.domicilioFiscal.numero}, ${data.domicilioFiscal.localidad}`;
              case "misfacilidades":
                return data.planesActivos.length > 0
                  ? `**Planes Activos**: ${data.planesActivos.map((p: any) => `${p.regimen} (${p.estadoPlan})`).join(", ")}`
                  : "No hay planes de pago activos.";
              case "deudavencimientos":
                return `**Saldo Total**: $${data.saldoTotal}\n- **Deudas Vencidas**: ${data.deudasVencidas.length}\n- **Próximo Vencimiento**: ${data.proximoVencimiento}`;
              case "rentascordoba":
                return `**Inscripción**: ${data.inscripcionIIBB.tipo}\n- **Estado**: ${data.inscripcionIIBB.estado}\n- **Saldo a Favor**: $${data.declaracionesJuradas.saldoAFavor}`;
              case "calendariovencimientosarca":
                return `**Periodo**: ${data.periodo}\n- **Vencimientos Próximos**: ${data.vencimientos
                  .slice(0, 3)
                  .map((v: any) => `${v.fecha}: ${v.obligacion}`)
                  .join(", ")}`;
              case "informefiscal":
                return `**Riesgo Fiscal [Score]**: ${data.metadata.scoreRiesgoFiscal}/100\n- **ID**: ${data.metadata.idReporte}\n- **Estado General**: ${data.resumenCumplimiento.map((r: any) => `${r.area}: ${r.estado}`).join(", ")}`;
              case "enviarmail":
                return `**ID Transacción**: ${data.transaccion.idEnvio}\n- **Archivo**: ${data.archivoAdjunto.nombre}\n- **Peso**: ${data.archivoAdjunto.tamaño}`;
              default:
                return "Resumen no disponible.";
            }
          };

          dataStream.write({
            type: "text-delta",
            id: textPartId,
            delta: `## Reporte Fiscal — CUIT ${cuit}\n\n`,
          });

          const allJsonReports: Array<{ tool: string; data: any }> = [];

          // ── Sequential (concatenated) tool execution ──────────────────────
          for (const cmd of commandNames) {
            const executor = FISCAL_COMMAND_MAP[cmd];
            if (!executor) continue;

            const label = LABEL_MAP[cmd] ?? cmd;
            const agentId = generateAgentId();
            const tasks = buildSubtasksForTool(cmd);
            const taskCount = tasks.length;

            // Notify client: session started
            dataStream.write({
              type: "data-agent-session-start",
              data: {
                agentId,
                toolName: label,
                toolKey: cmd,
                profileId: profileId ?? null,
                tasks: tasks.map((t) => ({ id: t.id, label: t.label })),
              },
            } as any);

            // Write the "agent working" marker text so the button appears
            dataStream.write({
              type: "text-delta",
              id: textPartId,
              delta: `_Agente trabajando en ${label}..._\n\n`,
            });

            const sessionStartMs = Date.now();

            if (cmd === "enviarmail") {
              // EnviarMail: single task, no real execution — emit completed immediately
              dataStream.write({
                type: "data-agent-task-update",
                data: {
                  agentId,
                  taskId: "task-0",
                  status: "running",
                  durationMs: undefined,
                  costCents: 0,
                },
              } as any);

              await new Promise((r) => setTimeout(r, 1000));

              dataStream.write({
                type: "data-agent-task-update",
                data: {
                  agentId,
                  taskId: "task-0",
                  status: "completed",
                  durationMs: 1000,
                  costCents: 0,
                },
              } as any);

              dataStream.write({
                type: "data-agent-session-complete",
                data: { agentId, durationMs: Date.now() - sessionStartMs },
              } as any);

              dataStream.write({
                type: "text-delta",
                id: textPartId,
                delta: `### 📧 ${label} · ⏱️ 0.5s · 👣 1 · 💰 $0\n> **Acción requerida**: Por favor, ingrese el mail de destino para enviar el reporte consolidado.\n\n[MAIL_INPUT_REPLACEMENT]\n\n`,
              });
              continue;
            }

            // ── Generic tool: distribute 5s across all tasks sequentially ──
            const delayPerTask = Math.floor(TOOL_MOCK_DELAY_MS / taskCount);

            for (let i = 0; i < tasks.length; i++) {
              const task = tasks[i];
              const taskStart = Date.now();

              // Task → running
              dataStream.write({
                type: "data-agent-task-update",
                data: { agentId, taskId: task.id, status: "running" },
              } as any);

              await new Promise((r) => setTimeout(r, delayPerTask));

              const taskDuration = Date.now() - taskStart;
              // Mock cost: 0.4 cents ($0.004) per subtask
              const costCents = cmd === "enviarmail" ? 0 : 0.4;

              // Task → completed
              dataStream.write({
                type: "data-agent-task-update",
                data: {
                  agentId,
                  taskId: task.id,
                  status: "completed",
                  durationMs: taskDuration,
                  costCents,
                },
              } as any);
            }

            // Execute the actual (mocked) function after the visual delay
            const data = await executor(cuit);
            const totalDurationMs = Date.now() - sessionStartMs;
            const duration = (totalDurationMs / 1000).toFixed(1);

            if (cmd !== "informefiscal") {
              allJsonReports.push({ tool: label, data });
            }

            // Notify client: session completed
            dataStream.write({
              type: "data-agent-session-complete",
              data: { agentId, durationMs: totalDurationMs },
            } as any);

            const totalCostCents =
              tasks.length * (cmd === "enviarmail" ? 0 : 0.4);
            const formattedCost = (totalCostCents / 100).toFixed(3);

            if (cmd === "informefiscal") {
              const enc = Buffer.from(JSON.stringify(allJsonReports)).toString(
                "base64"
              );
              const delta = `### 🔍 ${label} · ⏱️ ${duration}s · 👣 5 · 💰 $${formattedCost}\n\n<details><summary>📦 Ver JSON</summary>\n\n\`\`\`json\n${JSON.stringify(data, null, 2)}\n\`\`\`\n\n</details>\n\n[INFORME_FISCAL_BUTTON:${enc}]\n\n---\n\n`;
              dataStream.write({ type: "text-delta", id: textPartId, delta });
            } else {
              const delta = `### 🔍 ${label} · ⏱️ ${duration}s · 👣 5 · 💰 $${formattedCost}\n\n<details><summary>📦 Ver JSON</summary>\n\n\`\`\`json\n${JSON.stringify(data, null, 2)}\n\`\`\`\n\n</details>\n\n<details><summary>📋 Ver Reporte Formateado</summary>\n\n${formatSummary(cmd, data)}\n\n</details>\n\n---\n\n`;
              dataStream.write({ type: "text-delta", id: textPartId, delta });
            }
          }
          // ── End of sequential execution ───────────────────────────────────

          dataStream.write({ type: "text-end", id: textPartId });

          if (uiMessages.length === 1) {
            const now = new Date();
            const day = now.getDate().toString().padStart(2, "0");
            const month = (now.getMonth() + 1).toString().padStart(2, "0");
            const time = `${now.getHours().toString().padStart(2, "0")}:${now.getMinutes().toString().padStart(2, "0")}`;
            const timestamp = `${day}/${month} ${time}`;
            const title = `Informe ${cuit} — ${timestamp}`;
            dataStream.write({ type: "data-chat-title", data: title });
            try {
              await updateChatTitleById({ chatId: id, title });
            } catch (err) {
              console.error("Failed to save chat title:", err);
            }
          }
        },
        generateId: generateUUID,
      });

      return createUIMessageStreamResponse({ stream: streamInstance });
    }

    // Fallback: non-fiscal input
    const stream = createUIMessageStream({
      execute: async ({ writer: dataStream }) => {
        const textPartId = generateId();
        dataStream.write({ type: "text-start", id: textPartId });
        dataStream.write({
          type: "text-delta",
          id: textPartId,
          delta:
            "⚠️ **El sistema de Chat General está desactivado.**\n\nEste entorno está configurado exclusivamente como **Consola Fiscal**. Para generar un reporte, ingrese un CUIT seguido de los comandos deseados (ej: `20389727785 /ConsultaArca /RentasCordoba`).",
        });
        dataStream.write({ type: "text-end", id: textPartId });
      },
      generateId: generateUUID,
    });

    return createUIMessageStreamResponse({ stream });
  } catch (error) {
    console.error("Critical error in console API:", error);
    return new ChatbotError("offline:chat").toResponse();
  }
}

export async function DELETE(request: Request) {
  return Response.json({ success: true }, { status: 200 });
}
