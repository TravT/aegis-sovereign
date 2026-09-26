import React, { useEffect, useState, useRef } from 'react';
import { clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';

export interface OdometerProps extends React.HTMLAttributes<HTMLSpanElement> {
  value: number;
  prefix?: string;
  suffix?: string;
  durationMs?: number;
  decimals?: number;
}

export const Odometer: React.FC<OdometerProps> = ({
  value,
  prefix = '',
  suffix = '',
  durationMs = 1200,
  decimals = 0,
  className,
  ...props
}) => {
  const [displayValue, setDisplayValue] = useState<number>(value);
  const startValueRef = useRef<number>(value);
  const startTimeRef = useRef<number | null>(null);
  const frameRef = useRef<number | null>(null);

  useEffect(() => {
    startValueRef.current = displayValue;
    startTimeRef.current = null;

    const animate = (timestamp: number) => {
      if (!startTimeRef.current) startTimeRef.current = timestamp;
      const progress = Math.min(1, (timestamp - startTimeRef.current) / durationMs);

      // Ease Out Quartic
      const ease = 1 - Math.pow(1 - progress, 4);
      const current = startValueRef.current + (value - startValueRef.current) * ease;

      setDisplayValue(current);

      if (progress < 1) {
        frameRef.current = requestAnimationFrame(animate);
      } else {
        setDisplayValue(value);
      }
    };

    frameRef.current = requestAnimationFrame(animate);

    return () => {
      if (frameRef.current) cancelAnimationFrame(frameRef.current);
    };
  }, [value, durationMs]);

  const formattedNumber = displayValue.toLocaleString('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });

  return (
    <span
      className={twMerge(
        clsx(
          'font-mono tracking-tight font-semibold text-[#F3E5AB] transition-colors',
          className
        )
      )}
      {...props}
    >
      {prefix && <span className="opacity-80 mr-0.5">{prefix}</span>}
      <span>{formattedNumber}</span>
      {suffix && <span className="opacity-80 ml-0.5">{suffix}</span>}
    </span>
  );
};
