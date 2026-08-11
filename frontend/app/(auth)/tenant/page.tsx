import { OrganizationListWidget } from "@/components/auth/clerk-widgets";

export default function TenantSelectionPage() {
  return (
    <div className="flex w-full items-center justify-center">
      <OrganizationListWidget
        afterCreateOrganizationUrl="/chat"
        afterSelectOrganizationUrl="/chat"
        hidePersonal={true}
      />
    </div>
  );
}
