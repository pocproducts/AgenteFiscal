import { OrganizationList } from "@clerk/nextjs";

export default function TenantSelectionPage() {
  return (
    <div className="flex w-full items-center justify-center">
      <OrganizationList
        hidePersonal={true}
        afterSelectOrganizationUrl="/chat"
        afterCreateOrganizationUrl="/chat"
      />
    </div>
  );
}
