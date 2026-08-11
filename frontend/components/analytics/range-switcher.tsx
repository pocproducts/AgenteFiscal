import { cn } from "@/lib/utils";

export interface RangeOption {
  key: string;
  label: string;
}

export interface RangeSwitcherProps {
  options: RangeOption[];
  value: string;
  onChange: (key: string) => void;
}

export function RangeSwitcher({
  options,
  value,
  onChange,
}: RangeSwitcherProps) {
  return (
    <div className="inline-flex items-center gap-1 rounded-xl border border-border/60 bg-card/80 p-1 shadow-sm">
      {options.map((option) => {
        const active = option.key === value;
        return (
          <button
            className={cn(
              "rounded-lg px-2.5 py-1.5 text-xs font-bold transition-all",
              active
                ? "bg-primary text-primary-foreground shadow-sm"
                : "text-muted-foreground hover:bg-accent hover:text-foreground"
            )}
            key={option.key}
            onClick={() => onChange(option.key)}
            type="button"
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
