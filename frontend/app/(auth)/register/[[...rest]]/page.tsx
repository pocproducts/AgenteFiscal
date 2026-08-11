import { SignUpWidget } from "@/components/auth/clerk-widgets";

export default function RegisterPage() {
  return (
    <div className="flex w-full items-center justify-center">
      <SignUpWidget
        forceRedirectUrl="/chat"
        path="/register"
        routing="path"
        signInUrl="/login"
      />
    </div>
  );
}
