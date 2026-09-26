import React from 'react';
import { clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';

export type BadgeVariant = 'sovereign' | 'success' | 'danger' | 'warning' | 'neutral' | 'blue';
export type BadgeSize = 'sm' | 'md';

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: BadgeVariant;
  size?: BadgeSize;
  dot?: boolean;
  dotPulse?: boolean;
  icon?: React.ReactNode;
}

export const Badge: React.FC<BadgeProps> = ({
  children,
  className,
  variant = 'neutral',
  size = 'md',
  dot = false,
  dotPulse = true,
  icon,
  ...props
}) => {
  const baseClasses =
    'inline-flex items-center font-mono rounded font-medium uppercase tracking-wider select-none shrink-0';

  const sizeClasses: Record<BadgeSize, string> = {
    sm: 'px-2 py-0.5 text-[10px] gap-1.5',
    md: 'px-2.5 py-1 text-[11px] gap-2',
  };

  const variantClasses: Record<BadgeVariant, string> = {
    sovereign:
      'bg-[#D4AF37]/10 border border-[#D4AF37]/40 text-[#F3E5AB] shadow-[0_0_10px_rgba(212,175,55,0.15)]',
    success:
      'bg-[#00E676]/10 border border-[#00E676]/30 text-[#00E676] shadow-[0_0_10px_rgba(0,230,118,0.15)]',
    danger:
      'bg-[#FF5252]/10 border border-[#FF5252]/40 text-[#FF5252] shadow-[0_0_10px_rgba(255,82,82,0.15)]',
    warning:
      'bg-[#FFA726]/10 border border-[#FFA726]/40 text-[#FFA726] shadow-[0_0_10px_rgba(255,167,38,0.15)]',
    blue:
      'bg-[#2979FF]/10 border border-[#2979FF]/35 text-[#82B1FF]',
    neutral:
      'bg-[#141A24] border border-[#232B38] text-[#8B949E]',
  };

  const dotClasses: Record<BadgeVariant, string> = {
    sovereign: 'bg-[#D4AF37] shadow-[0_0_8px_#D4AF37]',
    success: 'bg-[#00E676] shadow-[0_0_8px_#00E676]',
    danger: 'bg-[#FF5252] shadow-[0_0_8px_#FF5252]',
    warning: 'bg-[#FFA726] shadow-[0_0_8px_#FFA726]',
    blue: 'bg-[#2979FF] shadow-[0_0_8px_#2979FF]',
    neutral: 'bg-[#8B949E]',
  };

  return (
    <span className={twMerge(clsx(baseClasses, sizeClasses[size], variantClasses[variant], className))} {...props}>
      {dot && (
        <span
          className={clsx(
            'w-1.5 h-1.5 rounded-full shrink-0',
            dotClasses[variant],
            dotPulse && 'animate-pulse'
          )}
        />
      )}
      {icon && <span className="shrink-0">{icon}</span>}
      <span>{children}</span>
    </span>
  );
};
