"use client";

import { Check, Loader2, Send } from "lucide-react";
import { useState } from "react";

export const MailSentStatus = ({ email }: { email: string }) => (
  <div className="mt-4 flex items-center gap-2 rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-emerald-500 animate-in fade-in zoom-in duration-300">
    <div className="flex size-6 items-center justify-center rounded-full bg-emerald-500 text-white">
      <Check size={14} />
    </div>
    <p className="text-sm font-medium">¡Reporte enviado con éxito a {email}!</p>
  </div>
);

export const MailInputComponent = (props: {
  chatId?: string;
  onSent?: (email: string) => void;
}) => {
  const { chatId, onSent } = props;
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState<"idle" | "sending" | "sent">("idle");

  const handleSend = async () => {
    if (!email.includes("@") || status !== "idle") {
      return;
    }
    setStatus("sending");
    try {
      if (chatId) {
        const res = await fetch(
          `${process.env.NEXT_PUBLIC_BASE_PATH ?? ""}/api/chat/${chatId}/mail`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email }),
          }
        );
        if (!res.ok) {
          throw new Error("mail-send-failed");
        }
      } else {
        await new Promise((r) => setTimeout(r, 1000));
      }
      setStatus("sent");
      onSent?.(email);
    } catch {
      setStatus("idle");
    }
  };

  if (status === "sent") {
    return <MailSentStatus email={email} />;
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
          type="button"
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
