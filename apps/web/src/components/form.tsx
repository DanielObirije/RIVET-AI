import { ComponentProps, ForwardedRef, forwardRef } from "react";
import {
  IconArrowBack,
  IconPaperclip,
  IconX,
} from "@tabler/icons-react";
import cx from "@/utils/cx";
import { ACCEPTED_EXTENSIONS, formatBytes } from "@/utils/attachments";

export interface AttachmentDraft {
  filename: string;
  size: number;
  progress: number | null;
}

export interface Props extends ComponentProps<"form"> {
  inputProps: ComponentProps<"input">;
  buttonProps: ComponentProps<"button">;
  attachment?: AttachmentDraft | null;
  attachmentError?: string | null;
  onSelectFile?: (file: File) => void;
  onRemoveAttachment?: () => void;
}

const Form = (
  {
    inputProps,
    buttonProps,
    onSubmit,
    attachment,
    attachmentError,
    onSelectFile,
    onRemoveAttachment,
  }: Props,
  ref: ForwardedRef<HTMLFormElement>,
) => {
  const uploading =
    attachment !== undefined &&
    attachment !== null &&
    attachment.progress !== null;

  return (
    <form onSubmit={onSubmit} className="m-auto w-full" ref={ref}>
      {attachment && (
        <div className="mb-2 flex items-center gap-2 rounded-xl border border-neutral-800 bg-neutral-900 px-3 py-2 text-sm text-neutral-300">
          <IconPaperclip size={16} stroke={1.5} className="shrink-0" />
          <span className="truncate">{attachment.filename}</span>
          <span className="shrink-0 text-neutral-500">
            {formatBytes(attachment.size)}
          </span>

          {uploading ? (
            <div className="ml-auto h-1 w-16 shrink-0 overflow-hidden rounded-full bg-neutral-800">
              <div
                className="h-full rounded-full bg-purple-500 transition-[width]"
                style={{
                  width: `${Math.round((attachment.progress ?? 0) * 100)}%`,
                }}
              />
            </div>
          ) : (
            <button
              type="button"
              onClick={onRemoveAttachment}
              aria-label="Remove attachment"
              className="ml-auto shrink-0 rounded p-1 text-neutral-400 hover:bg-neutral-800 hover:text-neutral-100"
            >
              <IconX size={16} />
            </button>
          )}
        </div>
      )}

      {attachmentError && (
        <p className="mb-2 text-sm text-red-400">{attachmentError}</p>
      )}

      <div className="relative flex items-center gap-4 justify-center">
        <label
          className={cx(
            "absolute left-2 z-10 flex size-7 md:size-8 items-center justify-center rounded-lg",
            "text-neutral-400 hover:bg-neutral-800 hover:text-neutral-100",
            inputProps.disabled || uploading
              ? "pointer-events-none opacity-40"
              : "cursor-pointer",
          )}
          aria-label="Attach a file"
        >
          <input
            type="file"
            accept={ACCEPTED_EXTENSIONS.join(",")}
            disabled={inputProps.disabled || uploading}
            className="sr-only"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) onSelectFile?.(file);
              event.target.value = "";
            }}
          />
          <IconPaperclip size={18} stroke={1.5} />
        </label>

        <input
          placeholder="Ask me anything..."
          required
          {...inputProps}
          className={cx(
            "transition h-10 md:h-12 pl-11 pr-12 flex-1 rounded-xl",
            "bg-neutral-900 border border-neutral-800 text-neutral-100",
            "placeholder:text-neutral-400",
            "hover:border-neutral-700 disabled:opacity-60",
            inputProps.className,
          )}
          type="text"
        />

        <button
          {...buttonProps}
          type="submit"
          tabIndex={-1}
          aria-label="Send message"
          className={cx(
            "absolute right-2 top-1/2 -translate-y-1/2",
            "flex items-center justify-center size-7 md:size-8 rounded-lg",
            "bg-purple-600 text-white hover:bg-purple-500",
            "disabled:opacity-40 disabled:hover:bg-purple-600",
            buttonProps.className,
          )}
        >
          <IconArrowBack stroke={1.5} />
        </button>
      </div>
    </form>
  );
};

export default forwardRef<HTMLFormElement, Props>(Form);
