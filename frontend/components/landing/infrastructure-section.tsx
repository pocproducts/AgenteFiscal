"use client";

import { useEffect, useRef, useState } from "react";
import { useLanguage } from "@/lib/i18n";

const locationMeta = [
  { city: "San Francisco", regionKey: "usWest", latency: "12ms" },
  { city: "New York", regionKey: "usEast", latency: "18ms" },
  { city: "London", regionKey: "europe", latency: "24ms" },
  { city: "Tokyo", regionKey: "asiaPacific", latency: "32ms" },
  { city: "Sydney", regionKey: "oceania", latency: "45ms" },
  { city: "Sao Paulo", regionKey: "southAmerica", latency: "38ms" },
] as const;

export function InfrastructureSection() {
  const { t } = useLanguage();
  const locations = locationMeta.map((l) => ({
    ...l,
    region: t.infrastructure.regions[l.regionKey],
  }));
  const [isVisible, setIsVisible] = useState(false);
  const [activeLocation, setActiveLocation] = useState(0);
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

  useEffect(() => {
    const interval = setInterval(() => {
      setActiveLocation((prev) => (prev + 1) % locations.length);
    }, 2000);
    return () => clearInterval(interval);
  }, [locations.length]);

  return (
    <section
      className="relative py-24 lg:py-32 overflow-hidden"
      ref={sectionRef}
    >
      <div className="max-w-[1400px] mx-auto px-6 lg:px-12">
        <div className="grid lg:grid-cols-2 gap-16 lg:gap-24 items-center">
          {/* Left: Content */}
          <div
            className={`transition-all duration-700 ${
              isVisible
                ? "opacity-100 translate-x-0"
                : "opacity-0 -translate-x-8"
            }`}
          >
            <span className="inline-flex items-center gap-3 text-sm font-mono text-muted-foreground mb-6">
              <span className="w-8 h-px bg-foreground/30" />
              {t.infrastructure.eyebrow}
            </span>
            <h2 className="text-4xl lg:text-6xl font-display tracking-tight mb-8">
              {t.infrastructure.titleLine1}
              <br />
              {t.infrastructure.titleLine2}
            </h2>
            <p className="text-xl text-muted-foreground leading-relaxed mb-12">
              {t.infrastructure.description}
            </p>

            {/* Stats */}
            <div className="grid grid-cols-3 gap-8">
              <div>
                <div className="text-4xl lg:text-5xl font-display mb-2">17</div>
                <div className="text-sm text-muted-foreground">
                  {t.infrastructure.stats.dataCenters}
                </div>
              </div>
              <div>
                <div className="text-4xl lg:text-5xl font-display mb-2">
                  99.99%
                </div>
                <div className="text-sm text-muted-foreground">
                  {t.infrastructure.stats.uptime}
                </div>
              </div>
              <div>
                <div className="text-4xl lg:text-5xl font-display mb-2">
                  &lt;50ms
                </div>
                <div className="text-sm text-muted-foreground">
                  {t.infrastructure.stats.latency}
                </div>
              </div>
            </div>
          </div>

          {/* Right: Location list */}
          <div
            className={`transition-all duration-700 delay-200 ${
              isVisible
                ? "opacity-100 translate-x-0"
                : "opacity-0 translate-x-8"
            }`}
          >
            <div className="border border-foreground/10">
              {/* Header */}
              <div className="px-6 py-4 border-b border-foreground/10 flex items-center justify-between">
                <span className="text-sm font-mono text-muted-foreground">
                  {t.infrastructure.edgeNetwork}
                </span>
                <span className="flex items-center gap-2 text-xs font-mono text-green-600">
                  <span className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
                  {t.infrastructure.allOperational}
                </span>
              </div>

              {/* Locations */}
              <div>
                {locations.map((location, index) => (
                  <div
                    className={`px-6 py-5 border-b border-foreground/5 last:border-b-0 flex items-center justify-between transition-all duration-300 ${
                      activeLocation === index ? "bg-foreground/[0.02]" : ""
                    }`}
                    key={location.city}
                  >
                    <div className="flex items-center gap-4">
                      <span
                        className={`w-2 h-2 rounded-full transition-colors duration-300 ${
                          activeLocation === index
                            ? "bg-foreground"
                            : "bg-foreground/20"
                        }`}
                      />
                      <div>
                        <div className="font-medium">{location.city}</div>
                        <div className="text-sm text-muted-foreground">
                          {location.region}
                        </div>
                      </div>
                    </div>
                    <span className="font-mono text-sm text-muted-foreground">
                      {location.latency}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
