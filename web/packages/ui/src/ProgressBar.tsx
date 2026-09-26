import React from 'react';
import { clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';

export type ProgressVariant = 'gold' | 'emerald' | 'danger';

export interface ProgressBarProps {
  value: number;
  max?: number;
  label?: React.ReactNode;
  stageLabel?: React.ReactNode;
  variant?: ProgressVariant;
  showPercentage?: boolean;
  animated?: boolean;
  className?: string;
}

export const ProgressBar: React.FC<ProgressBarProps> = ({
  value,
  max = 100,
  label,
  stageLabel,
  variant = 'gold',
  showPercentage = true,
  animated = true,
  className,
}) => {
  const percentage = Math.min(100, Math.max(0, Math.round((value / max) * 100)));

  const barVariants: Record<ProgressVariant, string> = {
    gold: 'bg-gradient-to-r from-[#B89325] via-[#D4AF37] to-[#F3E5AB] shadow-[0_0_12px_rgba(212,175,55,0.4)]',
    emerald:
      'bg-gradient-to-r from-[#065F46] via-[#10B981] to-[#00E676] shadow-[0_0_12px_rgba(0,230,118,0.4)]',
    danger:
      'bg-gradient-to-r from-[#7F1D1D] via-[#EF4444] to-[#FF5252] shadow-[0_0_12px_rgba(255,82,82,0.4)]',
  };

  return (
    <div className={twMerge('w-full flex flex-col gap-1.5', className)}>
      {(label || stageLabel || showPercentage) && (
        <div className="flex items-center justify-between text-xs font-mono">
          <div className="flex items-center gap-2">
            {label && <span className="text-[#E6EDF3] font-medium">{label}</span>}
            {stageLabel && <span className="text-[#8B949E] text-[11px]">{stageLabel}</span>}
          </div>
          {showPercentage && (
            <span className="text-[#F3E5AB] font-semibold">{percentage}%</span>
          )}
        </div>
      )}

      {/* Progress Track */}
      <div className="relative h-2 w-full bg-[#141A24] border border-[#232B38] rounded-full overflow-hidden">
        <div
          className={clsx(
            'h-full rounded-full transition-all duration-300 ease-out',
            barVariants[variant],
            animated && 'relative'
          )}
          style={{ width: `${percentage}%` }}
        >
          {animated && (
            <div className="absolute inset-0 bg-gradient-to-r from-transparent via-white/25 to-transparent animate-[shimmer_2s_infinite]" />
          )}
        </div>
      </div>
    </div>
  );
};
