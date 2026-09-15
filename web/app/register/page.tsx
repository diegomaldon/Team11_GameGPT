import type { Metadata } from 'next';
import { RegisterForm } from '@/components/auth/RegisterForm';

export const metadata: Metadata = {
  title: 'Create your account — GameGPT',
};

// Deliberately outside the (app) route group: that group wraps children in AppShell, which
// is the signed-in chrome. Registration is the one page you reach without an account.
export default function RegisterPage() {
  return (
    <main className="flex min-h-dvh flex-col justify-center px-5 py-10">
      <RegisterForm />
    </main>
  );
}
