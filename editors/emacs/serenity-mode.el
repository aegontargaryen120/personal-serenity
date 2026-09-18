;;; serenity-mode.el --- Major mode for the Serenity programming language -*- lexical-binding: t; -*-

;; Copyright (C) 2024

;; Author: Naad K Bhave
;; Version: 1.0.0
;; Package-Requires: ((emacs "25.1"))
;; Keywords: languages, serenity
;; URL: https://github.com/aegontargaryen120/personal-serenity.git

;;; Commentary:

;; This package provides a major mode for editing and interacting with
;; the Serenity programming language.  It includes syntax highlighting,
;; automatic indentation, REPL integration, and compilation support.
;;
;; Serenity is a custom language featuring:
;; - Functions defined with `func name() => ( ... )'
;; - Variables declared with `let x = value;'
;; - Control flow: if/else, while, for
;; - Built-in I/O (print, println) and string library
;; - Single-line comments (//) and block comments (/* */)

;;; Code:

(require 'comint)
(require 'compile)
(require 'imenu)

;; ─── Custom Variables ──────────────────────────────────────────────

(defgroup serenity nil
  "Major mode for the Serenity programming language."
  :group 'languages
  :prefix "serenity-")

(defcustom serenity-executable "python3"
  "Path to the Python interpreter used to run Serenity."
  :type 'string
  :group 'serenity)

(defcustom serenity-runner-file nil
  "Path to the Serenity runner entry point (the `serenity' script).
Used for compile and REPL commands.  If nil, the project root is
searched for the `serenity' runner automatically."
  :type '(choice (const nil) file)
  :group 'serenity)

(defcustom serenity-indent-offset 4
  "Number of spaces for each indentation level."
  :type 'integer
  :group 'serenity)

;; ─── Syntax Table ──────────────────────────────────────────────────

(defvar serenity-syntax-table
  (let ((table (make-syntax-table)))
    ;; Strings (double-quoted)
    (modify-syntax-entry ?\" "\"" table)

    ;; Single-line comments: //  and block comments: /* ... */
    (modify-syntax-entry ?/ ". 124" table)
    (modify-syntax-entry ?* ". 23" table)

    ;; Newline terminates single-line comments
    (modify-syntax-entry ?\n ">" table)

    ;; Underscores are word characters
    (modify-syntax-entry ?_ "w" table)

    table)
  "Syntax table for `serenity-mode'.")

;; ─── Font Lock (Syntax Highlighting) ───────────────────────────────

(defconst serenity-keywords
  '("func" "let" "if" "else" "while" "for" "return")
  "Serenity language keywords.")

(defconst serenity-builtins
  '("print" "println" "exit"
    "length" "charAt" "substring"
    "toUpper" "toLower" "trim"
    "contains" "indexOf" "toInt"
    "eval")
  "Serenity built-in functions.")

(defconst serenity-stdlib
  '("mult" "div" "abs" "min" "max" "min3" "max3"
    "clamp" "sign" "pow" "sqr" "cube" "mod"
    "even" "odd" "gcd" "lcm" "fact" "isPrime"
    "isBetween" "divisibleBy" "fib" "digitSum" "triangle"
    "isEmpty" "reverse" "startsWith" "endsWith" "repeat"
    "capitalize" "titleCase" "replace" "countOccurrences"
    "ltrim" "rtrim" "padLeft" "padRight" "truncate" "wordCount"
    "identity" "not" "bool" "isNull" "notNull"
    "isZero" "nonZero" "isEmptyText" "firstOf" "secondOf"
    "toggle" "isEqual" "isNotEqual" "countRange")
  "Function names provided by the Serenity standard library.")

(defconst serenity-constants
  '("true" "false" "null")
  "Serenity constants and literals.")

(defface serenity-operator-face
  '((t :inherit font-lock-comment-face :weight bold))
  "Face used to highlight operators and the => arrow."
  :group 'serenity)

(defvar serenity-font-lock-keywords
  `(
    ;; Preprocessor directives
    ("^%\\<[a-zA-Z]+\\>\\(?:\\s-+<[^>]+>\\)?" 0 'font-lock-preprocessor-face)

    ;; Keywords
    (,(regexp-opt serenity-keywords 'symbols) 0 'font-lock-keyword-face)

    ;; Built-in names
    (,(concat "\\<" (regexp-opt serenity-builtins t) "\\>") 0 'font-lock-builtin-face)

    ;; Standard-library names
    (,(concat "\\<" (regexp-opt serenity-stdlib t) "\\>") 0 'font-lock-builtin-face)

    ;; Constants and literals
    (,(regexp-opt serenity-constants 'symbols) 0 'font-lock-constant-face)

    ;; Function definitions: func name(...)
    ("\\<func\\>\\s-+\\(\\w+\\)" 1 'font-lock-function-name-face)

    ;; Function calls: name(
    ("\\<\\(\\w+\\)\\s-*(" 1 'font-lock-function-name-face)

    ;; String literals: "..." with escape sequences
    ("\"\\(?:[^\"\\\\]\\|\\\\[\"\\\\ntr]\\)*\"" 0 'font-lock-string-face)

    ;; Numeric literals
    ("\\<[0-9]+\\>" 0 'font-lock-constant-face)

    ;; => arrow
    ("=>" 0 'serenity-operator-face)

    ;; Post-increment and post-decrement: name++ / name--
    ("\\<\\w+\\>\\(?:++\\|--\\)" 0 'serenity-operator-face)
    )
  "Font-lock keywords for `serenity-mode'.")

;; ─── Indentation ───────────────────────────────────────────────────

(defun serenity--indent-level (line)
  "Return the indentation column of LINE.
Measures leading whitespace."
  (or (string-match-p "[^ \t]" line) 0))

(defun serenity--line-ends-with-arrow-p (line)
  "Return non-nil if LINE ends with =>, ignoring trailing whitespace."
  (string-match-p "=>[ \t]*\\'" line))

(defun serenity--line-ends-with-open-brace-p (line)
  "Return non-nil if LINE ends with an opening brace {."
  (string-match-p "{[ \t]*\\'" line))

(defun serenity--line-ends-with-open-paren-p (line)
  "Return non-nil if LINE ends with an opening paren (."
  (string-match-p "([ \t]*\\'" line))

(defun serenity--previous-non-empty-line ()
  "Get the contents of the previous non-empty line.
Returns \"\" if the current line is the first line in the buffer."
  (save-excursion
    (if (eq (forward-line -1) -1)
        "" ; already on the first line: no previous line exists
      (while (and (not (bobp))
                  (looking-at-p "^[ \t]*$"))
        (forward-line -1))
      (buffer-substring-no-properties
       (line-beginning-position)
       (line-end-position)))))

(defun serenity--lookup-indent ()
  "Compute the suggested indentation for the current line."
  (let* ((line (buffer-substring-no-properties
                (line-beginning-position) (line-end-position)))
         (only-closer (string-match-p "^[ \t]*[})]" line))
         (prev-line (serenity--previous-non-empty-line))
         (prev-indent (serenity--indent-level prev-line))
         (offset serenity-indent-offset))
    (cond
     ;; Line begins with a closing brace or paren: align with the block start
     (only-closer
      (max 0 (- prev-indent offset)))

     ;; Previous line ends with => (function body or control flow)
     ((serenity--line-ends-with-arrow-p prev-line)
      (+ prev-indent offset))

     ;; Previous line ends with {
     ((serenity--line-ends-with-open-brace-p prev-line)
      (+ prev-indent offset))

     ;; Previous line ends with (
     ((serenity--line-ends-with-open-paren-p prev-line)
      (+ prev-indent offset))

     ;; Inherit previous indentation
     (t prev-indent))))

(defun serenity-indent-line ()
  "Indent the current line according to Serenity conventions."
  (interactive)
  (unless (looking-at-p "^[ \t]*$")
    (let* ((cur-indent (serenity--indent-level
                        (buffer-substring-no-properties
                         (line-beginning-position) (line-end-position))))
           (suggested (serenity--lookup-indent)))
      (when (and (>= suggested 0) (not (eq cur-indent suggested)))
        (beginning-of-line)
        (delete-horizontal-space)
        (indent-to suggested)))))

;; ─── REPL (Comint) Integration ─────────────────────────────────────

(defvar serenity--repl-buffer nil
  "The current Serenity REPL buffer.")

(defun serenity--runner-script ()
  "Return the absolute path to the Serenity runner script.
That is `serenity-runner-file' when set, otherwise the `serenity' file
in the project root.  Signals an error when it cannot be found."
  (let* ((root (serenity--project-root))
         (script (or serenity-runner-file
                     (and root (expand-file-name "serenity" root)))))
    (unless (and script (file-exists-p script))
      (error "Cannot locate the Serenity runner (set `serenity-runner-file')"))
    script))

(defun serenity--runner-command ()
  "Return the shell words that invoke the Serenity runner.
List of `serenity-executable' followed by the runner script, so the
runner does not need to be directly executable."
  (list serenity-executable (serenity--runner-script)))

(defun serenity-repl ()
  "Start a Serenity REPL in a comint buffer.
Runs the Serenity runner with no arguments so that the interpreter
enters its `$' prompt loop."
  (interactive)
  (let ((repl-buf (get-buffer "*Serenity REPL*")))
    (if (and repl-buf (buffer-live-p repl-buf))
        (switch-to-buffer repl-buf)
      (let* ((root (serenity--project-root))
             (cmd (serenity--runner-command))
             (process-environment (append '("TERM=dumb")
                                          process-environment)))
        (unless root
          (error "Cannot start REPL: no Serenity project root found"))
        (let ((default-directory root))
          (setq serenity--repl-buffer
                (apply #'make-comint "Serenity REPL" (car cmd) nil
                       (cdr cmd))))
        (switch-to-buffer serenity--repl-buffer)
        (set-process-filter (get-buffer-process serenity--repl-buffer)
                            #'comint-output-filter)))))

(defun serenity--send-to-repl (text)
  "Send TEXT to the Serenity REPL process."
  (let ((proc (get-buffer-process serenity--repl-buffer)))
    (when (and proc (process-live-p proc))
      (comint-send-string proc (concat text "\n")))))

(defun serenity-send-buffer ()
  "Send the entire buffer to the Serenity REPL."
  (interactive)
  (unless (and serenity--repl-buffer
               (buffer-live-p serenity--repl-buffer))
    (serenity-repl))
  (serenity--send-to-repl (buffer-string))
  (message "Buffer sent to REPL"))

(defun serenity-send-region (start end)
  "Send the active region from START to END to the Serenity REPL."
  (interactive "r")
  (unless (and serenity--repl-buffer
               (buffer-live-p serenity--repl-buffer))
    (serenity-repl))
  (serenity--send-to-repl (buffer-substring-no-properties start end))
  (message "Region sent to REPL"))

(defun serenity-send-line ()
  "Send the current line to the Serenity REPL."
  (interactive)
  (unless (and serenity--repl-buffer
               (buffer-live-p serenity--repl-buffer))
    (serenity-repl))
  (serenity--send-to-repl
   (buffer-substring-no-properties
    (line-beginning-position) (line-end-position)))
  (message "Line sent to REPL"))

;; ─── Compilation ───────────────────────────────────────────────────

(defun serenity--project-root ()
  "Find the project root directory.
Walks up from the current buffer's file looking for the Serenity
runner script or the `src/' tree that marks a checkout."
  (let ((file (buffer-file-name)))
    (when file
      (let ((dir (file-name-directory file)))
        (while (and dir
                    (not (or (file-exists-p (expand-file-name "serenity" dir))
                             (file-exists-p (expand-file-name "src" dir)))))
          (setq dir (and (stringp dir)
                         (not (equal dir (file-name-directory
                                          (directory-file-name dir))))
                         (file-name-directory (directory-file-name dir)))))
        dir))))

(defun serenity--compile-command (file &optional run)
  "Shell command that compiles FILE to ARM64 assembly.
When RUN is non-nil, also assemble the output with `clang' and execute
the resulting binary."
  (let* ((asm (concat (file-name-base file) ".s"))
         (build (format "%s %s %s -o %s"
                        (shell-quote-argument serenity-executable)
                        (shell-quote-argument (serenity--runner-script))
                        (shell-quote-argument file)
                        (shell-quote-argument asm))))
    (if (not run)
        build
      (let* ((bin (make-temp-file "serenity-" nil ".out"))
             (binary (format "%s && clang %s -o %s"
                             build
                             (shell-quote-argument asm)
                             (shell-quote-argument bin))))
        (format "%s && %s" binary (shell-quote-argument bin))))))

(defun serenity-compile ()
  "Compile the current Serenity file to ARM64 assembly."
  (interactive)
  (save-buffer)
  (let ((file (buffer-file-name)))
    (unless file
      (error "Buffer is not visiting a file"))
    (compile (serenity--compile-command file))))

(defun serenity-compile-run ()
  "Compile the current Serenity file and run the resulting binary."
  (interactive)
  (save-buffer)
  (let ((file (buffer-file-name)))
    (unless file
      (error "Buffer is not visiting a file"))
    (compile (serenity--compile-command file t))))

(defun serenity-run ()
  "Run the interpreted Serenity REPL for the current buffer."
  (interactive)
  (serenity-repl))

;; ─── Navigation ────────────────────────────────────────────────────

(defun serenity-next-function ()
  "Move point to the next `func' definition."
  (interactive)
  (forward-line 1)
  (when (re-search-forward "^[ \t]*func[ \t]+\\w+" nil t)
    (goto-char (match-beginning 0))
    (beginning-of-line)))

(defun serenity-previous-function ()
  "Move point to the previous `func' definition."
  (interactive)
  (when (re-search-backward "^[ \t]*func[ \t]+\\w+" nil t)
    (beginning-of-line)))

;; ─── Comments ──────────────────────────────────────────────────────

(defun serenity-comment-dwim (arg)
  "Comment or uncomment the current line or region.
ARG is passed through to `comment-dwim'."
  (interactive "*P")
  (let ((comment-start "// ")
        (comment-end ""))
    (comment-dwim arg)))

;; ─── Imenu Support ─────────────────────────────────────────────────

(defvar serenity-imenu-generic-expression
  '(("Functions" "^[ \t]*func[ \t]+\\(\\w+\\)" 1))
  "Imenu pattern for finding function definitions.")

;; ─── Outlines (folding) ────────────────────────────────────────────

(defvar serenity-outline-regexp "^[ \t]*func ")

;; ─── Electric Pairs ────────────────────────────────────────────────

(defvar serenity-electric-pairs
  '((?\" . ?\") (?\( . ?\)) (?\{ . ?\}) (?\[ . ?\]))
  "Electric pair characters for Serenity.")

(defun serenity-electric-pair-mode ()
  "Enable buffer-local electric pairing for Serenity syntax characters."
  (interactive)
  (electric-pair-local-mode 1)
  (setq-local electric-pair-pairs serenity-electric-pairs))

;; ─── Keymap ────────────────────────────────────────────────────────

(defvar serenity-mode-map
  (let ((map (make-sparse-keymap)))
    (define-key map (kbd "C-c C-c") #'serenity-compile)
    (define-key map (kbd "C-c C-r") #'serenity-compile-run)

    ;; REPL
    (define-key map (kbd "C-c C-z") #'serenity-repl)
    (define-key map (kbd "C-c C-b") #'serenity-send-buffer)
    (define-key map (kbd "C-c C-e") #'serenity-send-line)
    (define-key map (kbd "C-c C-y") #'serenity-send-region)

    ;; Navigation
    (define-key map (kbd "C-c C-n") #'serenity-next-function)
    (define-key map (kbd "C-c C-p") #'serenity-previous-function)
    map)
  "Keymap for `serenity-mode'.")

;; ─── Minor Mode for REPL Interaction ───────────────────────────────

(define-minor-mode serenity-repl-minor-mode
  "Minor mode for Serenity REPL quick-send keybindings."
  :lighter " Sr:"
  :keymap (let ((map (make-sparse-keymap)))
            (define-key map (kbd "C-c C-s C-e") #'serenity-send-line)
            (define-key map (kbd "C-c C-s C-b") #'serenity-send-buffer)
            (define-key map (kbd "C-c C-s C-r") #'serenity-send-region)
            (define-key map (kbd "C-c C-s C-z") #'serenity-repl)
            map))

;; ─── Major Mode Definition ─────────────────────────────────────────

;;;###autoload
(define-derived-mode serenity-mode prog-mode "Serenity"
  "Major mode for editing Serenity source files.

\\{serenity-mode-map}"
  :syntax-table serenity-syntax-table

  ;; Font-lock
  (setq-local font-lock-defaults
              '(serenity-font-lock-keywords nil t nil nil))
  (setq-local font-lock-multiline t)

  ;; Indentation
  (setq-local indent-line-function #'serenity-indent-line)
  (setq-local indent-tabs-mode nil)
  (setq-local tab-width serenity-indent-offset)

  ;; Comments
  (setq-local comment-start "// ")
  (setq-local comment-end "")
  (setq-local comment-start-skip "//+\\s-*")
  (setq-local comment-column 40)

  ;; Imenu / Outline
  (setq-local imenu-generic-expression serenity-imenu-generic-expression)
  (setq-local outline-regexp serenity-outline-regexp)

  ;; Electric pairs
  (serenity-electric-pair-mode)

  ;; REPL minor mode
  (serenity-repl-minor-mode 1))

;;;###autoload
(add-to-list 'auto-mode-alist '("\\.serenity\\'" . serenity-mode))
(add-to-list 'auto-mode-alist '("\\.srn\\'" . serenity-mode))

;; ─── Provide ───────────────────────────────────────────────────────

(provide 'serenity-mode)

;;; serenity-mode.el ends here
