import type { Metadata } from 'next';
import { Geist, Geist_Mono } from 'next/font/google';
import './globals.css';

const geistSans = Geist({
  variable: '--font-geist-sans',
  subsets: ['latin'],
});

const geistMono = Geist_Mono({
  variable: '--font-geist-mono',
  subsets: ['latin'],
});

export const metadata: Metadata = {
  metadataBase: new URL(
    process.env.NEXT_PUBLIC_SITE_URL ?? 'http://localhost:3000',
  ),
  title: 'Sqwish GPU Slack Lab',
  description:
    'Explore the ex-VAT economics of sharing a four-GPU Sqwish research box through interruptible rentals.',
  openGraph: {
    title: 'Sqwish GPU Slack Lab',
    description:
      'Stress-test the ex-VAT economics of sharing four RTX PRO 6000 GPUs through interruptible rentals.',
    images: [{ url: '/og.png', width: 1536, height: 1024 }],
    type: 'website',
  },
  twitter: {
    card: 'summary_large_image',
    title: 'Sqwish GPU Slack Lab',
    description:
      'Stress-test a four-GPU research box with live owner-use, rental-fill, rate, discount, and storage assumptions.',
    images: ['/og.png'],
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased`}
      >
        {children}
      </body>
    </html>
  );
}
