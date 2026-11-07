import { ComponentProps, forwardRef } from "react";
import { IconArrowBack } from "@tabler/icons-react";
import cx from "@/utils/cx";

export interface Props extends ComponentProps<"form"> {
  inputProps: ComponentProps<"input">;
  buttonProps: ComponentProps<"button">;
}

const Form = ({ inputProps, buttonProps, onSubmit }: Props, ref: any) => {
  return (
    <form
      onSubmit={onSubmit}
      className="relative m-auto flex items-center gap-4 justify-center"
      ref={ref}
    >
      {/*<Avatar isUser={true} className="md:size-10 bg-gray-300" />*/}

      <input
        placeholder="Ask me anything..."
        required
        {...inputProps}
        className={cx(
          "transition h-10 md:h-12 pl-4 pr-12 flex-1 rounded-xl",
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
    </form>
  );
};

export default forwardRef(Form);
