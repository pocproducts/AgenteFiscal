import { AgentComposer } from "@/components/agent-launch/agent-composer";

export default function NewAgentPage() {
  return (
    <div className="flex flex-1 flex-col items-center justify-center bg-background/50 p-6">
      <div className="w-full max-w-2xl">
        <AgentComposer />
      </div>
    </div>
  );
}
