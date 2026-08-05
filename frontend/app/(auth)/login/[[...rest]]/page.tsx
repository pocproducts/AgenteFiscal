import { SignIn } from "@clerk/nextjs";

export default function LoginPage() {
  return (
    <div className="flex w-full items-center justify-center">
      <SignIn
        path="/login"
        routing="path"
        signUpUrl="/register"
        afterSignInUrl="/chat"
      />
    </div>
  );
}
