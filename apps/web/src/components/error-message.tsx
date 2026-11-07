import React from "react";
import { IconAlertTriangle, IconRefresh } from "@tabler/icons-react";

const ErrorMessage: React.FC<{
  message: string;
  onRetry: () => void;
  retrying?: boolean;
}> = ({ message, onRetry, retrying = false }) => {
  return (
    <article className="mb-4 flex items-start gap-4 p-4 md:p-5 rounded-2xl bg-neutral-900 border border-neutral-800">
      <div className="flex items-center justify-center size-8 shrink-0 rounded-full bg-purple-500/15 text-purple-300">
        <IconAlertTriangle size={18} />
      </div>

      <div className="flex-1 py-1.5 md:py-1">
        <p className="text-neutral-200">{message}</p>

        <button
          type="button"
          onClick={onRetry}
          disabled={retrying}
          className="mt-2 inline-flex items-center gap-1.5 text-sm font-medium text-purple-400 hover:text-purple-300 disabled:opacity-50"
        >
          <IconRefresh size={14} stroke={1.75} />
          Try again
        </button>
      </div>
    </article>
  );
};

export default ErrorMessage;
