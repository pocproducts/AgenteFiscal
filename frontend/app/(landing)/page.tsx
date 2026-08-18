import { CtaSection } from "@/components/landing/cta-section";
import { DevelopersSection } from "@/components/landing/developers-section";
import { FeaturesSection } from "@/components/landing/features-section";
import { FooterSection } from "@/components/landing/footer-section";
import { HeroSection } from "@/components/landing/hero-section";
import { HowItWorksSection } from "@/components/landing/how-it-works-section";
import { InfrastructureSection } from "@/components/landing/infrastructure-section";
import { IntegrationsSection } from "@/components/landing/integrations-section";
import { MetricsSection } from "@/components/landing/metrics-section";
import { Navigation } from "@/components/landing/navigation";
import { PricingSection } from "@/components/landing/pricing-section";
import { SecuritySection } from "@/components/landing/security-section";
import { TestimonialsSection } from "@/components/landing/testimonials-section";

export default function LandingPage() {
  return (
    <main className="relative min-h-screen overflow-x-hidden noise-overlay">
      <Navigation />
      <HeroSection />
      {/*<FeaturesSection />*/}
      <HowItWorksSection />
      {/*<InfrastructureSection />*/}
      {/*<MetricsSection />*/}
      {/*<IntegrationsSection />*/}
      {/*<SecuritySection />*/}
      {/*<DevelopersSection />*/}
      <TestimonialsSection />
      <PricingSection />
      <CtaSection />
      <FooterSection />
    </main>
  );
}
