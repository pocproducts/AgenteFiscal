"use client";

import { useEffect, useRef, useState } from "react";
import { useLanguage } from "@/lib/i18n";

function AnimatedCounter({
  end,
  suffix = "",
  prefix = "",
}: {
  end: number;
  suffix?: string;
  prefix?: string;
}) {
  const [count, setCount] = useState(0);
  const ref = useRef<HTMLDivElement>(null);
  const [hasAnimated, setHasAnimated] = useState(false);

  useEffect(() => {
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting && !hasAnimated) {
          setHasAnimated(true);
          const _start = 0;
          const duration = 2000;
          const startTime = performance.now();

          const animate = (currentTime: number) => {
            const elapsed = currentTime - startTime;
            const progress = Math.min(elapsed / duration, 1);
            const eased = 1 - (1 - progress) ** 3;
            setCount(Math.floor(eased * end));

            if (progress < 1) {
              requestAnimationFrame(animate);
            }
          };

          requestAnimationFrame(animate);
        }
      },
      { threshold: 0.5 }
    );

    if (ref.current) {
      observer.observe(ref.current);
    }
    return () => observer.disconnect();
  }, [end, hasAnimated]);

  return (
    <div className="text-6xl lg:text-8xl font-display tracking-tight" ref={ref}>
      {prefix}
      {count.toLocaleString()}
      {suffix}
    </div>
  );
}

const metrics = [
  {
    value: 2_847_392,
    suffix: "",
    prefix: "",
  },
  {
    value: 99,
    suffix: ".99%",
    prefix: "",
  },
  {
    value: 23,
    suffix: "ms",
    prefix: "",
  },
  {
    value: 184,
    suffix: "",
    prefix: "",
  },
];

export function MetricsSection() {
  const { t } = useLanguage();
  const [time, setTime] = useState<Date | null>(null);
  const [isVisible, setIsVisible] = useState(false);
  const sectionRef = useRef<HTMLElement>(null);

  useEffect(() => {
    setTime(new Date());
    const interval = setInterval(() => setTime(new Date()), 1000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setIsVisible(true);
        }
      },
      { threshold: 0.1 }
    );

    if (sectionRef.current) {
      observer.observe(sectionRef.current);
    }
    return () => observer.disconnect();
  }, []);

  return (
    <section
      className="relative py-24 lg:py-32 border-y border-foreground/10"
      id="studio"
      ref={sectionRef}
    >
      <div className="max-w-[1400px] mx-auto px-6 lg:px-12">
        {/* Header */}
        <div className="flex flex-col lg:flex-row lg:items-end lg:justify-between gap-8 mb-16 lg:mb-24">
          <div>
            <span className="inline-flex items-center gap-3 text-sm font-mono text-muted-foreground mb-6">
              <span className="w-8 h-px bg-foreground/30" />
              {t.metrics.eyebrow}
            </span>
            <h2
              className={`text-4xl lg:text-6xl font-display tracking-tight transition-all duration-700 ${
                isVisible
                  ? "opacity-100 translate-y-0"
                  : "opacity-0 translate-y-4"
              }`}
            >
              {t.metrics.titleLine1}
              <br />
              {t.metrics.titleLine2}
            </h2>
          </div>
          <div className="flex items-center gap-4 font-mono text-sm text-muted-foreground">
            <span className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
              {t.metrics.live}
            </span>
            <span className="text-foreground/30">|</span>
            <span>{time ? time.toLocaleTimeString() : ""}</span>
          </div>
        </div>

        {/* Metrics Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-px bg-foreground/10">
          {metrics.map((metric, index) => (
            <div
              className={`bg-background p-8 lg:p-12 transition-all duration-700 ${
                isVisible
                  ? "opacity-100 translate-y-0"
                  : "opacity-0 translate-y-8"
              }`}
              key={t.metrics.items[index]}
              style={{ transitionDelay: `${index * 100}ms` }}
            >
              <AnimatedCounter
                end={typeof metric.value === "number" ? metric.value : 0}
                prefix={metric.prefix}
                suffix={metric.suffix}
              />
              <div className="mt-4 text-lg text-muted-foreground">
                {t.metrics.items[index]}
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
