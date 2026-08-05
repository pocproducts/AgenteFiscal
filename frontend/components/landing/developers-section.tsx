"use client";

import { Check, Copy } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useLanguage } from "@/lib/i18n";

const codeExampleMeta = [
  {
    code: `npm install @optimus/sdk

# or
yarn add @optimus/sdk
pnpm add @optimus/sdk`,
  },
  {
    code: `import { Optimus } from '@optimus/sdk'

const optimus = new Optimus({
  apiKey: process.env.OPTIMUS_KEY
})`,
  },
  {
    code: `const app = await optimus.deploy({
  name: 'my-app',
  region: 'auto',
  scaling: {
    min: 1,
    max: 100
  }
})

console.log('Live at:', app.url)`,
  },
];

const codeAnimationStyles = `
  .dev-code-line {
    opacity: 0;
    transform: translateX(-8px);
    animation: devLineReveal 0.4s cubic-bezier(0.22, 1, 0.36, 1) forwards;
  }
  
  @keyframes devLineReveal {
    to {
      opacity: 1;
      transform: translateX(0);
    }
  }
  
  .dev-code-char {
    opacity: 0;
    filter: blur(8px);
    animation: devCharReveal 0.3s cubic-bezier(0.22, 1, 0.36, 1) forwards;
  }
  
  @keyframes devCharReveal {
    to {
      opacity: 1;
      filter: blur(0);
    }
  }
`;

export function DevelopersSection() {
  const { t } = useLanguage();
  const tabLabels = [
    t.developers.tabs.install,
    t.developers.tabs.initialize,
    t.developers.tabs.deploy,
  ];
  const codeExamples = codeExampleMeta.map((c, i) => ({
    ...c,
    label: tabLabels[i],
  }));
  const features = t.developers.features;
  const [activeTab, setActiveTab] = useState(0);
  const [copied, setCopied] = useState(false);
  const [isVisible, setIsVisible] = useState(false);
  const sectionRef = useRef<HTMLElement>(null);

  const handleCopy = () => {
    navigator.clipboard.writeText(codeExamples[activeTab].code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

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
      id="developers"
      ref={sectionRef}
    >
      <style dangerouslySetInnerHTML={{ __html: codeAnimationStyles }} />
      <div className="max-w-[1400px] mx-auto px-6 lg:px-12">
        <div className="grid lg:grid-cols-2 gap-16 lg:gap-24 items-start">
          {/* Left: Content */}
          <div
            className={`transition-all duration-700 ${
              isVisible
                ? "opacity-100 translate-y-0"
                : "opacity-0 translate-y-8"
            }`}
          >
            <span className="inline-flex items-center gap-3 text-sm font-mono text-muted-foreground mb-6">
              <span className="w-8 h-px bg-foreground/30" />
              {t.developers.eyebrow}
            </span>
            <h2 className="text-4xl lg:text-6xl font-display tracking-tight mb-8">
              {t.developers.titleLine1}
              <br />
              <span className="text-muted-foreground">
                {t.developers.titleLine2}
              </span>
            </h2>
            <p className="text-xl text-muted-foreground mb-12 leading-relaxed">
              {t.developers.description}
            </p>

            {/* Features */}
            <div className="grid grid-cols-2 gap-6">
              {features.map((feature, index) => (
                <div
                  className={`transition-all duration-500 ${
                    isVisible
                      ? "opacity-100 translate-y-0"
                      : "opacity-0 translate-y-4"
                  }`}
                  key={feature.title}
                  style={{ transitionDelay: `${index * 50 + 200}ms` }}
                >
                  <h3 className="font-medium mb-1">{feature.title}</h3>
                  <p className="text-sm text-muted-foreground">
                    {feature.description}
                  </p>
                </div>
              ))}
            </div>
          </div>

          {/* Right: Code block */}
          <div
            className={`lg:sticky lg:top-32 transition-all duration-700 delay-200 ${
              isVisible
                ? "opacity-100 translate-x-0"
                : "opacity-0 translate-x-8"
            }`}
          >
            <div className="border border-foreground/10">
              {/* Tabs */}
              <div className="flex items-center border-b border-foreground/10">
                {codeExamples.map((example, idx) => (
                  <button
                    className={`px-6 py-4 text-sm font-mono transition-colors relative ${
                      activeTab === idx
                        ? "text-foreground"
                        : "text-muted-foreground hover:text-foreground"
                    }`}
                    key={example.label}
                    onClick={() => setActiveTab(idx)}
                    type="button"
                  >
                    {example.label}
                    {activeTab === idx && (
                      <span className="absolute bottom-0 left-0 right-0 h-px bg-foreground" />
                    )}
                  </button>
                ))}
                <div className="flex-1" />
                <button
                  aria-label={t.developers.copyCode}
                  className="px-4 py-4 text-muted-foreground hover:text-foreground transition-colors"
                  onClick={handleCopy}
                  type="button"
                >
                  {copied ? (
                    <Check className="w-4 h-4 text-green-600" />
                  ) : (
                    <Copy className="w-4 h-4" />
                  )}
                </button>
              </div>

              {/* Code content */}
              <div className="p-8 font-mono text-sm bg-foreground/[0.01] min-h-[220px]">
                <pre className="text-foreground/80">
                  {codeExamples[activeTab].code
                    .split("\n")
                    .map((line, lineIndex) => (
                      <div
                        className="leading-loose dev-code-line"
                        key={`${activeTab}-${lineIndex}`}
                        style={{ animationDelay: `${lineIndex * 80}ms` }}
                      >
                        <span className="inline-flex">
                          {line.split("").map((char, charIndex) => (
                            <span
                              className="dev-code-char"
                              key={`${activeTab}-${lineIndex}-${charIndex}`}
                              style={{
                                animationDelay: `${lineIndex * 80 + charIndex * 15}ms`,
                              }}
                            >
                              {char === " " ? "\u00A0" : char}
                            </span>
                          ))}
                        </span>
                      </div>
                    ))}
                </pre>
              </div>
            </div>

            {/* Links */}
            <div className="mt-6 flex items-center gap-6 text-sm">
              <a
                className="text-foreground hover:underline underline-offset-4"
                href="#"
              >
                {t.developers.readDocs}
              </a>
              <span className="text-foreground/20">|</span>
              <a
                className="text-muted-foreground hover:text-foreground"
                href="#"
              >
                {t.developers.viewGitHub}
              </a>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
