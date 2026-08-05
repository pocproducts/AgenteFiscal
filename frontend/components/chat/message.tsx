"use client";
import type { UseChatHelpers } from "@ai-sdk/react";
import { Check, CheckCircle2, Loader2, Send } from "lucide-react";
import { useState } from "react";
import { useAgentSidebar } from "@/hooks/use-agent-sidebar";
import { useArtifact } from "@/hooks/use-artifact";
import type { Vote } from "@/lib/db/schema";
import type { ChatMessage } from "@/lib/types";
import { useLanguage } from "@/lib/i18n";
import { cn, sanitizeText } from "@/lib/utils";
import { MessageContent, MessageResponse } from "../ai-elements/message";
import { Shimmer } from "../ai-elements/shimmer";
import {
  Tool,
  ToolContent,
  ToolHeader,
  ToolInput,
  ToolOutput,
} from "../ai-elements/tool";
import { useDataStream } from "./data-stream-provider";
import { DocumentToolResult } from "./document";
import { DocumentPreview } from "./document-preview";
import { SparklesIcon } from "./icons";
import { MessageActions } from "./message-actions";
import { MessageReasoning } from "./message-reasoning";
import { PreviewAttachment } from "./preview-attachment";
import { Weather } from "./weather";

const AgenteTrabajandoButton = ({
  toolName,
  toolKey,
  messageId,
}: {
  toolName: string;
  toolKey: string;
  messageId: string;
}) => {
  const {
    allSessions,
    setActiveAgent,
    open: openAgentSidebar,
  } = useAgentSidebar();
  const { setArtifact } = useArtifact();

  // Find the session that matches this tool (by toolName from the stream)
  // We match by toolName since agentId is only known after the session-start event.
  const session =
    allSessions.find(
      (s) =>
        s.toolName.toLowerCase().replace(/[^a-z]/g, "") ===
        toolName.toLowerCase().replace(/[^a-z]/g, "")
    ) ?? null;

  const isCompleted = session?.status === "completed";
  const isRunning = session?.status === "running";

  const handleOpen = () => {
    setArtifact((prev) => ({ ...prev, isVisible: false }));
    if (session) {
      // Session already exists in store — just switch to it
      setActiveAgent(session.agentId);
    } else {
      // First click before stream event arrives — open optimistically
      openAgentSidebar(messageId, toolName, toolKey);
    }
  };

  return (
    <button
      className={cn(
        "inline-flex items-center gap-2 my-1.5 px-3 py-1.5 rounded-lg border font-medium text-xs text-left w-fit transition-all duration-300 shadow-sm hover:shadow-md active:scale-[0.98]",
        isCompleted
          ? "border-emerald-500/30 bg-emerald-500/10 hover:bg-emerald-500/15 text-emerald-600 dark:text-emerald-400"
          : "border-primary/20 bg-primary/5 hover:bg-primary/10 text-primary cursor-pointer"
      )}
      onClick={handleOpen}
      type="button"
    >
      {isCompleted ? (
        <CheckCircle2 className="size-3.5 text-emerald-500 shrink-0" />
      ) : (
        <Loader2 className="size-3.5 animate-spin text-primary shrink-0" />
      )}
      <span className={cn("italic", isCompleted && "not-italic font-semibold")}>
        {isCompleted
          ? `${toolName} completado ✓`
          : `Agente trabajando en ${toolName}...`}
      </span>
    </button>
  );
};

const PurePreviewMessage = ({
  addToolApprovalResponse,
  chatId,
  message,
  vote,
  isLoading,
  setMessages: _setMessages,
  regenerate: _regenerate,
  isReadonly,
  requiresScrollPadding: _requiresScrollPadding,
  onEdit,
}: {
  addToolApprovalResponse: UseChatHelpers<ChatMessage>["addToolApprovalResponse"];
  chatId: string;
  message: ChatMessage;
  vote: Vote | undefined;
  isLoading: boolean;
  setMessages: UseChatHelpers<ChatMessage>["setMessages"];
  regenerate: UseChatHelpers<ChatMessage>["regenerate"];
  isReadonly: boolean;
  requiresScrollPadding: boolean;
  onEdit?: (message: ChatMessage) => void;
}) => {
  const attachmentsFromMessage = (message.parts ?? []).filter(
    (part) => part.type === "file"
  );

  useDataStream();

  const isUser = message.role === "user";
  const isAssistant = message.role === "assistant";

  const hasAnyContent = message.parts?.some(
    (part) =>
      (part.type === "text" && part.text?.trim().length > 0) ||
      (part.type === "reasoning" &&
        "text" in part &&
        part.text?.trim().length > 0) ||
      part.type.startsWith("tool-")
  );
  const isThinking = isAssistant && isLoading && !hasAnyContent;
  const { t } = useLanguage();

  const attachments = attachmentsFromMessage.length > 0 && (
    <div
      className="flex flex-row justify-end gap-2"
      data-testid={"message-attachments"}
    >
      {attachmentsFromMessage.map((attachment) => (
        <PreviewAttachment
          attachment={{
            name: attachment.filename ?? "file",
            contentType: attachment.mediaType,
            url: attachment.url,
          }}
          key={attachment.url}
        />
      ))}
    </div>
  );

  const mergedReasoning = message.parts?.reduce(
    (acc, part) => {
      if (part.type === "reasoning" && part.text?.trim().length > 0) {
        return {
          text: acc.text ? `${acc.text}\n\n${part.text}` : part.text,
          isStreaming: "state" in part ? part.state === "streaming" : false,
          rendered: false,
        };
      }
      return acc;
    },
    { text: "", isStreaming: false, rendered: false }
  ) ?? { text: "", isStreaming: false, rendered: false };

  const parts = message.parts?.map((part, index) => {
    const { type } = part;
    const key = `message-${message.id}-part-${index}`;

    if (type === "reasoning") {
      if (!mergedReasoning.rendered && mergedReasoning.text) {
        mergedReasoning.rendered = true;
        return (
          <MessageReasoning
            isLoading={isLoading || mergedReasoning.isStreaming}
            key={key}
            reasoning={mergedReasoning.text}
          />
        );
      }
      return null;
    }

    if (type === "text") {
      const RE =
        /(\[MAIL_INPUT_REPLACEMENT\]|\[INFORME_FISCAL_BUTTON:[A-Za-z0-9+/=]+\]|_(?:Agente trabajando en .*?\.\.\.)_)/g;
      const fragments = part.text.split(RE);

      return (
        <MessageContent
          className={cn("text-[13px] leading-[1.65]", {
            "w-fit max-w-[min(80%,56ch)] overflow-hidden break-words rounded-2xl rounded-br-lg border border-border/30 bg-gradient-to-br from-secondary to-muted px-3.5 py-2 shadow-[var(--shadow-card)]":
              message.role === "user",
          })}
          data-testid="message-content"
          key={key}
        >
          {fragments.map((fragment, i) => {
            if (!fragment) return null;

            if (fragment === "[MAIL_INPUT_REPLACEMENT]") {
              return <MailInputComponent key={i} />;
            }
            if (fragment.startsWith("[INFORME_FISCAL_BUTTON:")) {
              const b64 = fragment
                .replace("[INFORME_FISCAL_BUTTON:", "")
                .replace("]", "");
              return <InformeFiscalButton dataEncoded={b64} key={i} />;
            }
            if (
              fragment.startsWith("_Agente trabajando en ") &&
              fragment.endsWith("..._")
            ) {
              const match = fragment.match(
                /^_Agente trabajando en (.*?)\.\.\._$/
              );
              const toolName = match ? match[1] : "";
              const nameLower = toolName.toLowerCase();
              if (
                nameLower === "enviarmail" ||
                nameLower.includes("informefiscal") ||
                nameLower.includes("informe fiscal")
              ) {
                return null;
              }
              // Derive the toolKey by stripping spaces and lowercasing
              const toolKey = toolName.replace(/\s+/g, "").toLowerCase();
              return (
                <AgenteTrabajandoButton
                  key={i}
                  messageId={message.id}
                  toolKey={toolKey}
                  toolName={toolName}
                />
              );
            }
            return (
              <MessageResponse key={i}>
                {sanitizeText(fragment)}
              </MessageResponse>
            );
          })}
        </MessageContent>
      );
    }

    if (type === "tool-getWeather") {
      const { toolCallId, state } = part;
      const approvalId = (part as { approval?: { id: string } }).approval?.id;
      const isDenied =
        state === "output-denied" ||
        (state === "approval-responded" &&
          (part as { approval?: { approved?: boolean } }).approval?.approved ===
            false);
      const widthClass = "w-[min(100%,450px)]";

      if (state === "output-available") {
        return (
          <div className={widthClass} key={toolCallId}>
            <Weather weatherAtLocation={part.output} />
          </div>
        );
      }

      if (isDenied) {
        return (
          <div className={widthClass} key={toolCallId}>
            <Tool className="w-full" defaultOpen={true}>
              <ToolHeader state="output-denied" type="tool-getWeather" />
              <ToolContent>
                <div className="px-4 py-3 text-muted-foreground text-sm">
                  {t.panel.chat.toolApproval.weatherDenied}
                </div>
              </ToolContent>
            </Tool>
          </div>
        );
      }

      if (state === "approval-responded") {
        return (
          <div className={widthClass} key={toolCallId}>
            <Tool className="w-full" defaultOpen={true}>
              <ToolHeader state={state} type="tool-getWeather" />
              <ToolContent>
                <ToolInput input={part.input} />
              </ToolContent>
            </Tool>
          </div>
        );
      }

      return (
        <div className={widthClass} key={toolCallId}>
          <Tool className="w-full" defaultOpen={true}>
            <ToolHeader state={state} type="tool-getWeather" />
            <ToolContent>
              {(state === "input-available" ||
                state === "approval-requested") && (
                <ToolInput input={part.input} />
              )}
              {state === "approval-requested" && approvalId && (
                <div className="flex items-center justify-end gap-2 border-t px-4 py-3">
                  <button
                    className="rounded-md px-3 py-1.5 text-muted-foreground text-sm transition-colors hover:bg-muted hover:text-foreground"
                    onClick={() => {
                      addToolApprovalResponse({
                        id: approvalId,
                        approved: false,
                        reason: "User denied weather lookup",
                      });
                    }}
                    type="button"
                  >
                    {t.panel.chat.toolApproval.deny}
                  </button>
                  <button
                    className="rounded-md bg-primary px-3 py-1.5 text-primary-foreground text-sm transition-colors hover:bg-primary/90"
                    onClick={() => {
                      addToolApprovalResponse({
                        id: approvalId,
                        approved: true,
                      });
                    }}
                    type="button"
                  >
                    {t.panel.chat.toolApproval.allow}
                  </button>
                </div>
              )}
            </ToolContent>
          </Tool>
        </div>
      );
    }

    const FISCAL_TOOL_LABELS: Record<string, string> = {
      "tool-consultaArca": "ConsultaArca",
      "tool-sistemaRegistral": "SistemaRegistral",
      "tool-misFacilidades": "MisFacilidades",
      "tool-deudaVencimientos": "DeudaVencimientos",
      "tool-rentasCordoba": "RentasCordoba",
      "tool-calendarioVencimientosArca": "CalendarioVencimientosArca",
    };

    if (part.type === ("tool-invocation" as any)) {
      const toolPart = part as any;
      const { toolCallId, state, toolName } = toolPart;
      const toolType = `tool-${toolName}`;

      if (toolType in FISCAL_TOOL_LABELS) {
        const label = FISCAL_TOOL_LABELS[toolType];

        return (
          <div className="w-full max-w-xl" key={toolCallId}>
            <Tool className="w-full" defaultOpen={true}>
              <ToolHeader state={state} type={toolType as any} />
              <ToolContent>
                {state === "input-available" && (
                  <ToolInput input={toolPart.input} />
                )}
                {state === "output-available" && (
                  <div className="px-4 py-3 space-y-1">
                    <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-2">
                      {label}
                    </p>
                    <ToolOutput
                      errorText={undefined}
                      output={toolPart.output}
                    />
                  </div>
                )}
              </ToolContent>
            </Tool>
          </div>
        );
      }
    }

    if (type === "tool-createDocument") {
      const { toolCallId } = part;

      if (part.output && "error" in part.output) {
        return (
          <div
            className="rounded-lg border border-red-200 bg-red-50 p-4 text-red-500 dark:bg-red-950/50"
            key={toolCallId}
          >
            {t.panel.chat.document.errorCreating}: {String(part.output.error)}
          </div>
        );
      }

      return (
        <DocumentPreview
          isReadonly={isReadonly}
          key={toolCallId}
          result={part.output}
        />
      );
    }

    if (type === "tool-updateDocument") {
      const { toolCallId } = part;

      if (part.output && "error" in part.output) {
        return (
          <div
            className="rounded-lg border border-red-200 bg-red-50 p-4 text-red-500 dark:bg-red-950/50"
            key={toolCallId}
          >
            {t.panel.chat.document.errorUpdating}: {String(part.output.error)}
          </div>
        );
      }

      return (
        <div className="relative" key={toolCallId}>
          <DocumentPreview
            args={{ ...part.output, isUpdate: true }}
            isReadonly={isReadonly}
            result={part.output}
          />
        </div>
      );
    }

    if (type === "tool-requestSuggestions") {
      const { toolCallId, state } = part;

      return (
        <Tool
          className="w-[min(100%,450px)]"
          defaultOpen={true}
          key={toolCallId}
        >
          <ToolHeader state={state} type="tool-requestSuggestions" />
          <ToolContent>
            {state === "input-available" && <ToolInput input={part.input} />}
            {state === "output-available" && (
              <ToolOutput
                errorText={undefined}
                output={
                  "error" in part.output ? (
                    <div className="rounded border p-2 text-red-500">
                      {t.panel.chat.document.error}: {String(part.output.error)}
                    </div>
                  ) : (
                    <DocumentToolResult
                      isReadonly={isReadonly}
                      result={part.output}
                      type="request-suggestions"
                    />
                  )
                }
              />
            )}
          </ToolContent>
        </Tool>
      );
    }

    return null;
  });

  const actions = !isReadonly && (
    <MessageActions
      chatId={chatId}
      isLoading={isLoading}
      key={`action-${message.id}`}
      message={message}
      onEdit={onEdit ? () => onEdit(message) : undefined}
      vote={vote}
    />
  );

  const content = isThinking ? (
    <div className="flex h-[calc(13px*1.65)] items-center text-[13px] leading-[1.65]">
      <Shimmer className="font-medium" duration={1}>
        {t.panel.chat.reasoning.thinking}
      </Shimmer>
    </div>
  ) : (
    <>
      {attachments}
      {parts}
      {actions}
    </>
  );

  return (
    <div
      className={cn(
        "group/message w-full",
        !isAssistant && "animate-[fade-up_0.25s_cubic-bezier(0.22,1,0.36,1)]"
      )}
      data-role={message.role}
      data-testid={`message-${message.role}`}
    >
      <div
        className={cn(
          isUser ? "flex flex-col items-end gap-2" : "flex items-start gap-3"
        )}
      >
        {isAssistant && (
          <div className="flex h-[calc(13px*1.65)] shrink-0 items-center">
            <div className="flex size-7 items-center justify-center rounded-lg bg-muted/60 text-muted-foreground ring-1 ring-border/50">
              <SparklesIcon size={13} />
            </div>
          </div>
        )}
        {isAssistant ? (
          <div className="flex min-w-0 flex-1 flex-col gap-2">{content}</div>
        ) : (
          content
        )}
      </div>
    </div>
  );
};

export const PreviewMessage = PurePreviewMessage;

export const ThinkingMessage = () => {
  const { t } = useLanguage();
  return (
    <div
      className="group/message w-full"
      data-role="assistant"
      data-testid="message-assistant-loading"
    >
      <div className="flex items-start gap-3">
        <div className="flex h-[calc(13px*1.65)] shrink-0 items-center">
          <div className="flex size-7 items-center justify-center rounded-lg bg-muted/60 text-muted-foreground ring-1 ring-border/50">
            <SparklesIcon size={13} />
          </div>
        </div>

        <div className="flex h-[calc(13px*1.65)] items-center text-[13px] leading-[1.65]">
          <Shimmer className="font-medium" duration={1}>
            {t.panel.chat.reasoning.thinking}
          </Shimmer>
        </div>
      </div>
    </div>
  );
};
const MailInputComponent = () => {
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState<"idle" | "sending" | "sent">("idle");

  const handleSend = async () => {
    if (!email.includes("@")) return;
    setStatus("sending");
    await new Promise((r) => setTimeout(r, 2000));
    setStatus("sent");
  };

  if (status === "sent") {
    return (
      <div className="mt-4 flex items-center gap-2 rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-emerald-500 animate-in fade-in zoom-in duration-300">
        <div className="flex size-6 items-center justify-center rounded-full bg-emerald-500 text-white">
          <Check size={14} />
        </div>
        <p className="text-sm font-medium">
          ¡Reporte enviado con éxito a {email}!
        </p>
      </div>
    );
  }

  return (
    <div className="mt-4 flex flex-col gap-3 rounded-2xl border border-border/40 bg-muted/30 p-4 shadow-sm transition-all hover:bg-muted/50">
      <div className="flex items-center gap-2 px-1">
        <Send className="text-muted-foreground" size={14} />
        <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground/80">
          Destinatario del Reporte
        </span>
      </div>
      <div className="flex gap-2 max-w-sm">
        <input
          className="h-10 flex-1 rounded-xl border border-border/50 bg-background px-4 text-sm outline-none transition-all focus:border-primary/50 focus:ring-4 focus:ring-primary/5"
          disabled={status === "sending"}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="ejemplo@fiscal.arca.gob.ar"
          type="email"
          value={email}
        />
        <button
          className="flex h-10 items-center justify-center gap-2 rounded-xl bg-primary px-5 text-sm font-medium text-primary-foreground transition-all hover:opacity-90 active:scale-95 disabled:pointer-events-none disabled:opacity-50"
          disabled={status === "sending" || !email.includes("@")}
          onClick={handleSend}
        >
          {status === "sending" ? (
            <>
              <Loader2 className="animate-spin" size={14} />
              Enviando...
            </>
          ) : (
            <>
              <Send size={14} />
              Enviar
            </>
          )}
        </button>
      </div>
      <p className="px-1 text-[11px] text-muted-foreground/60 italic">
        * El reporte consolidado se adjuntará automáticamente en formato PDF.
      </p>
    </div>
  );
};

const InformeFiscalButton = ({ dataEncoded }: { dataEncoded: string }) => {
  const [open, setOpen] = useState(false);
  let reports: Array<{ tool: string; data: any }> = [];
  try {
    const jsonStr = atob(dataEncoded);
    reports = JSON.parse(jsonStr);
  } catch (e) {
    console.error("Failed to parse reports", e);
  }

  const renderNaturalLanguage = (tool: string, data: any) => {
    switch (tool.toLowerCase()) {
      case "consultaarca":
        return (
          <div className="space-y-4 text-sm text-black">
            <p>
              El CUIT <strong>{data.cuit}</strong> pertenece a{" "}
              <strong>{data.denominacion}</strong>, registrado actualmente como{" "}
              <strong>{data.condicionFiscal}</strong>.
            </p>
            <div>
              <p className="font-semibold mb-1">Obligaciones Impositivas:</p>
              <ul className="list-disc pl-5 space-y-1">
                {data.obligaciones.map((ob: any, i: number) => (
                  <li key={i}>
                    <strong>{ob.impuesto}</strong> ({ob.periodicidad}): Estado{" "}
                    <em>{ob.estado}</em>
                    {ob.vencimientoProximo && (
                      <span>
                        {" "}
                        — Próximo vencimiento el {ob.vencimientoProximo}
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        );
      case "sistemaregistral":
        return (
          <div className="space-y-4 text-sm text-black">
            <p>
              La entidad <strong>{data.razonSocial}</strong> es una{" "}
              <strong>{data.formaJuridica}</strong> inscripta desde{" "}
              <strong>{data.fechaInscripcionAFIP}</strong>.
            </p>
            <div>
              <p className="font-semibold mb-1">Actividades Registradas:</p>
              <ul className="list-disc pl-5 space-y-1">
                <li>
                  <strong>Principal:</strong>{" "}
                  {data.actividadPrincipal.descripcion}
                </li>
                {data.actividadesSecundarias.map((act: any, i: number) => (
                  <li key={i}>
                    <strong>Secundaria:</strong> {act.descripcion}
                  </li>
                ))}
              </ul>
            </div>
            <p>
              Su domicilio fiscal verificado se encuentra en{" "}
              <strong>
                {data.domicilioFiscal.calle} {data.domicilioFiscal.numero},{" "}
                {data.domicilioFiscal.localidad},{" "}
                {data.domicilioFiscal.provincia}
              </strong>
              .
            </p>
          </div>
        );
      case "misfacilidades":
        return (
          <div className="space-y-4 text-sm text-black">
            <p>Estado en el sistema de facilidades de pago:</p>
            {data.planesActivos.length > 0 ? (
              <ul className="space-y-3">
                {data.planesActivos.map((plan: any, i: number) => (
                  <li
                    className="bg-white p-3 rounded border border-gray-200"
                    key={i}
                  >
                    <p className="font-semibold">
                      {plan.regimen} (Plan N° {plan.nroPlan})
                    </p>
                    <p>
                      El plan se encuentra <strong>{plan.estadoPlan}</strong>.
                      Se ha pagado la cuota {plan.cuotasPagadas} de{" "}
                      {plan.cuotasTotales} ($
                      {plan.montoCuotaActual.toLocaleString()}).
                    </p>
                    <p>
                      El próximo vencimiento de cuota es el{" "}
                      <strong>{plan.proximoVencimientoCuota}</strong>.
                    </p>
                  </li>
                ))}
              </ul>
            ) : (
              <p>
                No se registran planes de facilidades activos en este momento.
              </p>
            )}
          </div>
        );
      case "deudavencimientos":
        return (
          <div className="space-y-4 text-sm text-black">
            <p>
              El saldo total de deuda registrado es de{" "}
              <strong>${data.saldoTotal.toLocaleString()}</strong>.
            </p>
            {data.deudasVencidas.length > 0 && (
              <div>
                <p className="font-semibold mb-1">Deudas ya vencidas:</p>
                <ul className="list-disc pl-5 space-y-1">
                  {data.deudasVencidas.map((deuda: any, i: number) => (
                    <li key={i}>
                      {deuda.impuesto} ({deuda.periodo}):{" "}
                      <strong>${deuda.total.toLocaleString()}</strong> (Se
                      encuentra <em>{deuda.estadoCobranza}</em> desde{" "}
                      {deuda.fechaVencimiento})
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {data.deudasPendientes.length > 0 && (
              <div>
                <p className="font-semibold mb-1">
                  Obligaciones pendientes (no vencidas):
                </p>
                <ul className="list-disc pl-5 space-y-1">
                  {data.deudasPendientes.map((deuda: any, i: number) => (
                    <li key={i}>
                      {deuda.impuesto} ({deuda.periodo}):{" "}
                      <strong>${deuda.total.toLocaleString()}</strong> a vencer
                      el {deuda.fechaVencimiento}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        );
      case "rentascordoba":
        return (
          <div className="space-y-4 text-sm text-black">
            <p>
              En Rentas de la Provincia de Córdoba, el contribuyente figura bajo
              el <strong>{data.inscripcionIIBB.tipo}</strong> con estado{" "}
              <strong>{data.inscripcionIIBB.estado}</strong>.
            </p>
            <p>
              La última DDJJ informada corresponde a{" "}
              <strong>{data.declaracionesJuradas.ultimaDeclarada}</strong>,
              resultando en{" "}
              <strong>{data.declaracionesJuradas.estadoCuenta}</strong> con un
              saldo a favor de{" "}
              <strong>${data.declaracionesJuradas.saldoAFavor}</strong>.
            </p>
            {data.actividades.length > 0 && (
              <p>
                La actividad gravada es &quot;{data.actividades[0].descripcion}
                &quot; a una alícuota del {data.actividades[0].alicuota}.
              </p>
            )}
          </div>
        );
      case "calendariovencimientosarca":
        return (
          <div className="space-y-4 text-sm text-black">
            <p>
              Detalle de vencimientos para el periodo{" "}
              <strong>{data.periodo}</strong>:
            </p>
            <ul className="space-y-2">
              {data.vencimientos.map((venc: any, i: number) => (
                <li
                  className="flex justify-between items-center border-b border-gray-200 pb-2 last:border-0 last:pb-0"
                  key={i}
                >
                  <span>
                    <strong>{venc.fecha}</strong> — {venc.obligacion}
                  </span>
                  <span className="text-xs px-2 py-1 rounded bg-gray-100 text-black">
                    {venc.estado}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        );
      default:
        return (
          <pre className="overflow-x-auto rounded-xl border border-gray-200 bg-white p-4 text-[11px] leading-snug text-black shadow-inner no-scrollbar">
            <code>{JSON.stringify(data, null, 2)}</code>
          </pre>
        );
    }
  };

  return (
    <div className="mt-4 flex flex-col gap-2">
      <button
        className="flex w-fit h-10 items-center justify-center gap-2 rounded-xl bg-black px-5 text-sm font-medium text-white transition-all hover:opacity-90 active:scale-95 border border-black"
        onClick={() => setOpen(!open)}
      >
        📋 {open ? "Ocultar Informe Fiscal" : "Ver Informe Fiscal Completo ..."}
      </button>

      {open && (
        <div className="mt-2 flex flex-col gap-6 rounded-2xl border border-gray-300 bg-white p-6 shadow-sm overflow-hidden animate-in slide-in-from-top-2 fade-in duration-200">
          <div className="flex items-center justify-between border-b border-gray-300 pb-4">
            <h3 className="text-xl font-semibold tracking-tight text-black">
              Informe Consolidado Completo
            </h3>
          </div>
          <div className="flex flex-col gap-6 max-h-[600px] overflow-y-auto no-scrollbar pr-2">
            {reports.map((report, idx) => (
              <div
                className="rounded-2xl border border-gray-300 bg-white p-5 shadow-sm"
                key={idx}
              >
                <h4 className="mb-4 text-xs font-bold uppercase tracking-[0.15em] text-black border-b border-gray-200 pb-2">
                  {report.tool}
                </h4>
                {renderNaturalLanguage(report.tool, report.data)}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};
