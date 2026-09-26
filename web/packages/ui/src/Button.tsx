import React, { forwardRef } from 'react';
import { clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';
import { Loader2 } from 'lucide-react';

export type ButtonVariant = 'gold' | 'outline' | 'ghost' | 'danger' | 'emerald';
export type ButtonSize = 'sm' | 'md' | 'lg';

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
  icon?: React.ReactNode;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  (
    {
      children,
      className,
      variant = 'gold',
      size = 'md',
      loading = false,
      disabled = false,
      icon,
      ...props
    },
    ref
  ) => {
    const baseClasses =
      'inline-flex items-center justify-center font-medium rounded-md transition-all duration-200 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-offset-[#07090D] disabled:opacity-50 disabled:cursor-not-allowed select-none';

    const sizeClasses: Record<ButtonSize, string> = {
      sm: 'px-2.5 py-1.5 text-xs gap-1.5',
      md: 'px-4 py-2 text-xs font-semibold tracking-wide gap-2',
      lg: 'px-6 py-3 text-sm font-semibold tracking-wider gap-2.5',
    };

    const variantClasses: Record<ButtonVariant, string> = {
      gold: 'bg-gradient-to-r from-[#D4AF37] to-[#B89325] text-black hover:from-[#F3E5AB] hover:to-[#D4AF37] shadow-[0_0_15px_rgba(212,175,55,0.25)] hover:shadow-[0_0_22px_rgba(212,175,55,0.4)] focus:ring-[#D4AF37] font-semibold border border-[#F3E5AB]/40 active:translate-y-[1px]',
      outline:
        'bg-[#0E121A]/80 border border-[#D4AF37]/40 text-[#F3E5AB] hover:bg-[#D4AF37]/15 hover:border-[#D4AF37] hover:shadow-[0_0_15px_rgba(212,175,55,0.2)] focus:ring-[#D4AF37] active:translate-y-[1px]',
      ghost:
        'bg-transparent text-[#8B949E] hover:text-[#E6EDF3] hover:bg-[#141A24] border border-transparent focus:ring-[#232B38]',
      danger:
        'bg-[#FF5252]/15 border border-[#FF5252]/40 text-[#FF5252] hover:bg-[#FF5252]/25 hover:border-[#FF5252] focus:ring-[#FF5252] shadow-[0_0_12px_rgba(255,82,82,0.2)]',
      emerald:
        'bg-[#10B981]/15 border border-[#10B981]/40 text-[#00E676] hover:bg-[#10B981]/25 hover:border-[#00E676] focus:ring-[#10B981] shadow-[0_0_12px_rgba(0,230,118,0.2)]',
    };

    return (
      <button
        ref={ref}
        disabled={disabled || loading}
        className={twMerge(clsx(baseClasses, sizeClasses[size], variantClasses[variant], className))}
        {...props}
      >
        {loading ? (
          <Loader2 className="w-4 h-4 animate-spin" />
        ) : icon ? (
          <span className="shrink-0">{icon}</span>
        ) : null}
        {children}
      </button>
    );
  }
);

Button.displayName = 'Button';
