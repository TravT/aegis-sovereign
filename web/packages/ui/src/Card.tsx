import React from 'react';
import { clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';

export type CardVariant = 'default' | 'gold-accent' | 'critical' | 'interactive';

export interface CardProps extends Omit<React.HTMLAttributes<HTMLDivElement>, 'title'> {
  variant?: CardVariant;
  title?: React.ReactNode;
  subtitle?: React.ReactNode;
  headerRight?: React.ReactNode;
  icon?: React.ReactNode;
}

export const Card: React.FC<CardProps> = ({
  children,
  className,
  variant = 'default',
  title,
  subtitle,
  headerRight,
  icon,
  ...props
}) => {
  const baseClasses =
    'rounded-lg bg-[#0E121A] border transition-all duration-200 overflow-hidden flex flex-col';

  const variantClasses: Record<CardVariant, string> = {
    default: 'border-[#232B38] shadow-[0_4px_20px_rgba(0,0,0,0.4)]',
    'gold-accent':
      'border-[#D4AF37]/35 shadow-[0_4px_24px_rgba(212,175,55,0.12)] hover:border-[#D4AF37]/60 hover:shadow-[0_4px_30px_rgba(212,175,55,0.2)]',
    critical:
      'border-[#FF5252]/40 bg-gradient-to-r from-[#FF5252]/10 to-[#0E121A] shadow-[0_4px_20px_rgba(255,82,82,0.15)]',
    interactive:
      'border-[#232B38] hover:border-[#D4AF37]/50 hover:bg-[#141A24] cursor-pointer shadow-[0_4px_20px_rgba(0,0,0,0.4)] hover:shadow-[0_4px_24px_rgba(212,175,55,0.15)]',
  };

  const hasHeader = title || headerRight || icon;

  return (
    <div className={twMerge(clsx(baseClasses, variantClasses[variant], className))} {...props}>
      {hasHeader && (
        <div className="px-4 py-3 border-b border-[#232B38] bg-white/[0.02] flex items-center justify-between gap-3">
          <div className="flex items-center gap-2.5 min-w-0">
            {icon && <span className="text-[#D4AF37] shrink-0">{icon}</span>}
            <div className="min-w-0">
              {title && (
                <h3 className="font-serif text-xs md:text-sm font-semibold tracking-wider text-[#F3E5AB] uppercase truncate">
                  {title}
                </h3>
              )}
              {subtitle && (
                <p className="text-[11px] text-[#8B949E] tracking-tight truncate">
                  {subtitle}
                </p>
              )}
            </div>
          </div>
          {headerRight && <div className="shrink-0">{headerRight}</div>}
        </div>
      )}
      <div className="p-4 flex-1">{children}</div>
    </div>
  );
};
