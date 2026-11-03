import type { Metadata } from 'next';
import { AuthLayout } from '@/components/auth/AuthLayout';
import { RegisterForm } from '@/components/auth/RegisterForm';

export const metadata: Metadata = {
  title: 'Create your account — GameGPT',
};

// Deliberately outside the (app) route group: that group wraps children in AppShell, which
// is the signed-in chrome. Registration is the one page you reach without an account.
// TM11-142: same split layout as sign-in.
export default function RegisterPage() {
  return (
    <AuthLayout>
      <RegisterForm />
    </AuthLayout>
  );
}
