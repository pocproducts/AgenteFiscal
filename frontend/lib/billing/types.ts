export type BillingPlanId = "Free" | "Pro" | "Enterprise";

export interface BillingState {
  tokenBalance: number;
  usdBalance: number;
  currentPlan: BillingPlanId;
}
