import { SignInWidget } from "@/components/auth/clerk-widgets";

export default function LoginPage() {
  return (
    <div className="flex w-full items-center justify-center">
      <SignInWidget
        forceRedirectUrl="/chat"
        path="/login"
        routing="path"
        signUpUrl="/register"
      />
    </div>
  );
}
