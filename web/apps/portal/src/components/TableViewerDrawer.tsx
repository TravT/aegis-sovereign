'use client';

import React, { useState, useMemo } from 'react';
import { Table as TableIcon, Download, Search, X, Check } from 'lucide-react';
import { Drawer, Button } from '@aegis/ui';

export interface TableViewerDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  title: string;
  markdownContent?: string;
  structuredRows?: Array<Record<string, string>>;
}

interface ParsedTable {
  headers: string[];
  rows: string[][];
}

function parseMarkdownTable(markdown: string): ParsedTable {
  if (!markdown) return { headers: [], rows: [] };

  const lines = markdown.split('\n');
  const headers: string[] = [];
  const rows: string[][] = [];
  let foundHeader = false;

  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (line.startsWith('|') && line.endsWith('|')) {
      // Check if separator line (|---|---|)
      if (/^\|[\s:\-|]+\|$/.test(line)) {
        continue;
      }

      const cells = line
        .slice(1, -1)
        .split('|')
        .map((c) => c.trim().replace(/`/g, '').replace(/\*\*/g, ''));

      if (!foundHeader) {
        headers.push(...cells);
        foundHeader = true;
      } else {
        rows.push(cells);
      }
    }
  }

  return { headers, rows };
}

export const TableViewerDrawer: React.FC<TableViewerDrawerProps> = ({
  isOpen,
  onClose,
  title,
  markdownContent = '',
  structuredRows,
}) => {
  const [searchTerm, setSearchTerm] = useState<string>('');
  const [downloadSuccess, setDownloadSuccess] = useState<boolean>(false);

  // Parse markdown table or use structured rows
  const parsedTable = useMemo<ParsedTable>(() => {
    if (structuredRows && structuredRows.length > 0) {
      const headers = Object.keys(structuredRows[0]);
      const rows = structuredRows.map((r) => headers.map((h) => r[h] || ''));
      return { headers, rows };
    }
    return parseMarkdownTable(markdownContent);
  }, [markdownContent, structuredRows]);

  // Filter rows based on search
  const filteredRows = useMemo(() => {
    if (!searchTerm.trim()) return parsedTable.rows;
    const term = searchTerm.toLowerCase();
    return parsedTable.rows.filter((row) =>
      row.some((cell) => cell.toLowerCase().includes(term))
    );
  }, [parsedTable.rows, searchTerm]);

  // CSV Export handler
  const handleExportCsv = () => {
    if (parsedTable.headers.length === 0) return;

    const escapeCsv = (str: string) => {
      const escaped = str.replace(/"/g, '""');
      return `"${escaped}"`;
    };

    const headerLine = parsedTable.headers.map(escapeCsv).join(',');
    const rowLines = parsedTable.rows.map((row) => row.map(escapeCsv).join(','));
    const csvContent = [headerLine, ...rowLines].join('\r\n');

    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.setAttribute('download', `${title.toLowerCase().replace(/[^a-z0-9]/g, '_')}_export.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);

    setDownloadSuccess(true);
    setTimeout(() => setDownloadSuccess(false), 2500);
  };

  return (
    <Drawer
      isOpen={isOpen}
      onClose={onClose}
      title={title || 'STRUCTURED TABLE VIEWER'}
      subtitle="Multi-column tabular layout with horizontal scrolling and 1-click CSV export"
      icon={<TableIcon className="w-5 h-5 text-[#00E676]" />}
      width="xl"
    >
      <div className="space-y-4 text-xs text-[#E6EDF3]">
        {/* Controls Bar: Search & Export */}
        <div className="flex flex-wrap items-center justify-between gap-3 p-3 rounded-lg bg-[#141A24] border border-[#232B38]">
          <div className="relative flex-1 min-w-[220px]">
            <input
              type="text"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              placeholder="Filtrar dados da tabela..."
              className="w-full pl-8 pr-3 py-1.5 bg-[#0E121A] border border-[#232B38] rounded text-xs text-[#E6EDF3] placeholder-[#8B949E] focus:outline-none focus:border-[#00E676]"
            />
            <Search className="w-3.5 h-3.5 text-[#8B949E] absolute left-2.5 top-2" />
          </div>

          <div className="flex items-center gap-2">
            <span className="font-mono text-[11px] text-[#8B949E]">
              {filteredRows.length} de {parsedTable.rows.length} linhas
            </span>

            <Button
              variant="gold"
              size="sm"
              icon={downloadSuccess ? <Check className="w-3.5 h-3.5 text-black" /> : <Download className="w-3.5 h-3.5 text-black" />}
              onClick={handleExportCsv}
              disabled={parsedTable.headers.length === 0}
            >
              {downloadSuccess ? 'CSV Exportado!' : 'Exportar CSV'}
            </Button>
          </div>
        </div>

        {/* Responsive Table Container */}
        {parsedTable.headers.length > 0 ? (
          <div className="border border-[#232B38] rounded-lg overflow-x-auto shadow-inner bg-[#07090D] max-h-[65vh]">
            <table className="w-full border-collapse text-left text-xs">
              <thead className="sticky top-0 bg-[#0E121A] border-b border-[#232B38] z-10">
                <tr>
                  {parsedTable.headers.map((h, idx) => (
                    <th
                      key={idx}
                      className="px-4 py-2.5 font-mono text-[11px] font-bold text-[#F3E5AB] uppercase tracking-wider whitespace-nowrap"
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-[#232B38]/60 font-sans">
                {filteredRows.map((row, rIdx) => (
                  <tr
                    key={rIdx}
                    className={`transition-colors hover:bg-white/[0.04] ${
                      rIdx % 2 === 0 ? 'bg-[#0E121A]/70' : 'bg-[#141A24]/50'
                    }`}
                  >
                    {row.map((cell, cIdx) => (
                      <td
                        key={cIdx}
                        className="px-4 py-2 text-[#E6EDF3] leading-relaxed whitespace-nowrap"
                      >
                        {cell}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="p-8 text-center text-[#8B949E] font-mono text-xs border border-dashed border-[#232B38] rounded-lg">
            Nenhuma estrutura tabular markdown foi detectada neste registro.
          </div>
        )}
      </div>
    </Drawer>
  );
};
