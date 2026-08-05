"use client";

import { useEffect, useRef, useState } from "react";
import { useLanguage } from "@/lib/i18n";

const integrationMeta = [
  { name: "GitHub", categoryKey: "versionControl" },
  { name: "Slack", categoryKey: "communication" },
  { name: "Stripe", categoryKey: "payments" },
  { name: "PostgreSQL", categoryKey: "database" },
  { name: "Redis", categoryKey: "cache" },
  { name: "AWS", categoryKey: "cloud" },
  { name: "MongoDB", categoryKey: "database" },
  { name: "Vercel", categoryKey: "hosting" },
  { name: "Figma", categoryKey: "design" },
  { name: "Linear", categoryKey: "projectManagement" },
  { name: "Notion", categoryKey: "documentation" },
  { name: "OpenAI", categoryKey: "aiml" },
] as const;

export function IntegrationsSection() {
  const { t } = useLanguage();
  const integrations = integrationMeta.map((i) => ({
    name: i.name,
    category: t.integrations.categories[i.categoryKey],
  }));
  const [isVisible, setIsVisible] = useState(false);
  const sectionRef = useRef<HTMLElement>(null);

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
      className="relative py-24 lg:py-32 overflow-hidden"
      id="integrations"
      ref={sectionRef}
    >
      <div className="max-w-[1400px] mx-auto px-6 lg:px-12">
        {/* Header */}
        <div
          className={`text-center max-w-3xl mx-auto mb-16 lg:mb-24 transition-all duration-700 ${
            isVisible ? "opacity-100 translate-y-0" : "opacity-0 translate-y-8"
          }`}
        >
          <span className="inline-flex items-center gap-3 text-sm font-mono text-muted-foreground mb-6">
            <span className="w-8 h-px bg-foreground/30" />
            {t.integrations.eyebrow}
            <span className="w-8 h-px bg-foreground/30" />
          </span>
          <h2 className="text-4xl lg:text-6xl font-display tracking-tight mb-6">
            {t.integrations.titleLine1}
            <br />
            {t.integrations.titleLine2}
          </h2>
          <p className="text-xl text-muted-foreground">
            {t.integrations.description}
          </p>
        </div>
      </div>

      {/* Full-width marquees outside container */}
      <div className="w-full mb-6">
        <div className="flex gap-6 marquee">
          {[...new Array(2)].map((_, setIndex) => (
            <div className="flex gap-6 shrink-0" key={setIndex}>
              {integrations.map((integration) => (
                <div
                  className="shrink-0 px-8 py-6 border border-foreground/10 hover:border-foreground/30 hover:bg-foreground/[0.02] transition-all duration-300 group"
                  key={`${integration.name}-${setIndex}`}
                >
                  <div className="text-lg font-medium group-hover:translate-x-1 transition-transform">
                    {integration.name}
                  </div>
                  <div className="text-sm text-muted-foreground">
                    {integration.category}
                  </div>
                </div>
              ))}
            </div>
          ))}
        </div>
      </div>

      {/* Reverse marquee */}
      <div className="w-full">
        <div className="flex gap-6 marquee-reverse">
          {[...new Array(2)].map((_, setIndex) => (
            <div className="flex gap-6 shrink-0" key={setIndex}>
              {[...integrations].reverse().map((integration) => (
                <div
                  className="shrink-0 px-8 py-6 border border-foreground/10 hover:border-foreground/30 hover:bg-foreground/[0.02] transition-all duration-300 group"
                  key={`${integration.name}-reverse-${setIndex}`}
                >
                  <div className="text-lg font-medium group-hover:translate-x-1 transition-transform">
                    {integration.name}
                  </div>
                  <div className="text-sm text-muted-foreground">
                    {integration.category}
                  </div>
                </div>
              ))}
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
