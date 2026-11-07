import React from "react";
import Markdown from "markdown-to-jsx";
import cx from "@/utils/cx";
import { Message as MessageProps } from "ai/react";
import RivetLogo from "@/components/rivet-logo";
import { IconUser } from "@tabler/icons-react";

const Message: React.FC<MessageProps> = ({ content, role }) => {
  const isUser = role === "user";

  return (
    <article
      className={cx(
        "mb-4 flex items-start gap-4 p-4 md:p-5 rounded-2xl",
        isUser
          ? "bg-neutral-800/50"
          : "bg-neutral-900 border border-neutral-800",
      )}
    >
      <Avatar isUser={isUser} />
      <Markdown
        className={cx(
          "py-1.5 md:py-1 space-y-4 text-neutral-100",
          "[&_code]:rounded [&_code]:bg-neutral-800 [&_code]:px-1.5 [&_code]:py-0.5 [&_code]:text-[0.9em] [&_code]:text-purple-200",
          "[&_pre]:overflow-x-auto [&_pre]:rounded-xl [&_pre]:border [&_pre]:border-neutral-800 [&_pre]:bg-neutral-950 [&_pre]:p-4 [&_pre]:text-sm",
          "[&_pre_code]:bg-transparent [&_pre_code]:p-0 [&_pre_code]:text-neutral-200",
          isUser ? "font-semibold" : "",
        )}
        options={{
          overrides: {
            ol: ({ children }) => <ol className="list-decimal">{children}</ol>,
            ul: ({ children }) => <ol className="list-disc">{children}</ol>,
          },
        }}
      >
        {content}
      </Markdown>
    </article>
  );
};

const Avatar: React.FC<{ isUser?: boolean; className?: string }> = ({
  isUser = false,
  className,
}) => {
  return (
    <div
      className={cx(
        "flex items-center justify-center size-8 shrink-0 rounded-full",
        isUser ? "bg-neutral-800 text-neutral-200" : "bg-purple-600 text-white",
        className,
      )}
    >
      {isUser ? <IconUser size={20} /> : <RivetLogo />}
    </div>
  );
};

export default Message;
export { Avatar };
