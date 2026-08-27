/**
 * The Longeron launcher tile: open the SysML model workbench WITHOUT a
 * notebook.
 *
 * ipylab 1.1 exposes no `ILauncher` surface to kernels (verified against
 * its bundle), so this tiny STATIC extension owns the tile; everything
 * after the click is the kernel-side app's job (`longeron.app.open()` is
 * idempotent: it replaces + reveals its one sidebar panel).
 *
 * Click behavior (the `longeron:launch` command):
 *
 * 1. ensure the dedicated console session exists -- `console:create`
 *    with the constant path `longeron-app` and the DEFAULT python
 *    kernelspec.  A console (not a bare session) is deliberate: the
 *    ipywidgets frontend manager only attaches to notebook/console
 *    session contexts, and ipylab's docking rides on widget comms, so a
 *    bare `sessions.startNew` would execute fine and dock nothing.  The
 *    console tab is the app's honest engine room (and a live handle:
 *    the launch code binds `app` in its namespace).  It opens
 *    UNFOCUSED (`activate: false`): the action lands in the sidebar,
 *    not the main area.
 * 2. execute `longeron.app.open(layout="lab")` on that kernel --
 *    `layout="lab"` on purpose, so a kernel without ipylab raises the
 *    package's own MissingExtraError (which names the exact pip
 *    command) instead of silently rendering an inline widget nobody
 *    can see;
 * 3. surface progress honestly: an in-progress toast while the kernel
 *    starts, success when the sidebar is up, and an error toast carrying
 *    the kernel's ename/evalue (plus a pip-install hint when the import
 *    itself failed) otherwise.
 *
 * Reuse semantics: one session, ever.  Within a page lifetime the plugin
 * remembers its console; across reloads the console tracker is searched
 * for a panel on the `longeron-app` path; and even when the console
 * WIDGET was closed, `console:create` on the same path reconnects to the
 * still-running session (JupyterLab's SessionContext finds running
 * sessions by path) -- so a second click re-executes the idempotent
 * kernel-side open, which replaces and reveals the existing sidebar
 * panel instead of duplicating anything.
 */

import {
  JupyterFrontEnd,
  JupyterFrontEndPlugin
} from '@jupyterlab/application';
import { ICommandPalette, ISessionContext, Notification } from '@jupyterlab/apputils';
import { IConsoleTracker } from '@jupyterlab/console';
import { ILauncher } from '@jupyterlab/launcher';
import { Kernel, KernelMessage } from '@jupyterlab/services';
import { LabIcon } from '@jupyterlab/ui-components';

/** The command id (distinct from the kernel-registered `longeron:open-app`). */
const COMMAND_ID = 'longeron:launch';

/** The one session every click funnels into (also the reuse key). */
const SESSION_PATH = 'longeron-app';

/** What the click runs in the kernel; `app` stays bound for console users. */
const OPEN_CODE = 'import longeron.app\napp = longeron.app.open(layout="lab")';

/** The fix-it hint when the kernel cannot even import longeron. */
const INSTALL_HINT = 'pip install "longeron[explorer]"';

/**
 * The longeron monogram, VERBATIM from `longeron.app._ICON_SVG` (two part
 * boxes joined by a composition diamond and a routed edge).  `width="16"`
 * mirrors the builtin Lab icons' intrinsic sizing; `jp-icon3` follows the
 * Lab theme.  tests/test_labextension.py guards against drift.
 */
const ICON_SVG = `<svg xmlns="http://www.w3.org/2000/svg" width="16" viewBox="0 0 24 24">
  <g class="jp-icon3" fill="#616161">
    <rect x="3" y="3" width="9.5" height="7" rx="1.2"/>
    <path d="M7.75 10.1 9.55 12 7.75 13.9 5.95 12z"/>
    <path d="M6.9 13.6h1.7v2.2h2.9v1.7H6.9z"/>
    <rect x="11.5" y="14" width="9.5" height="7" rx="1.2"/>
  </g>
</svg>
`;

export const longeronIcon = new LabIcon({
  name: 'longeron:launcher-icon',
  svgstr: ICON_SVG
});

/** The slice of ConsolePanel this plugin touches (keeps deps type-only). */
interface IConsoleLike {
  readonly isDisposed: boolean;
  readonly sessionContext: ISessionContext;
}

/** A kernel-side failure, distilled for the toast. */
class KernelExecuteError extends Error {
  constructor(ename: string, evalue: string) {
    const hint =
      ename === 'ModuleNotFoundError' && evalue.includes('longeron')
        ? ` — install it in this kernel's environment with: ${INSTALL_HINT}`
        : '';
    super(`${ename}: ${evalue}${hint}`);
  }
}

/**
 * Run the open code on the kernel; reject with the kernel's own error.
 *
 * `store_history: false` keeps the console's In[n] counter untouched;
 * the traceback (if any) goes to IOPub, which the console does not echo
 * for foreign executes -- the toast is the error surface.
 */
async function executeOpen(kernel: Kernel.IKernelConnection): Promise<void> {
  const future = kernel.requestExecute(
    { code: OPEN_CODE, store_history: false, stop_on_error: false },
    false
  );
  let iopubErrors: { ename: string; evalue: string }[] = [];
  future.onIOPub = (msg): void => {
    if (KernelMessage.isErrorMsg(msg)) {
      iopubErrors = [{ ename: msg.content.ename, evalue: msg.content.evalue }];
    }
  };
  const reply = (await future.done) as KernelMessage.IExecuteReplyMsg;
  const content = reply.content as unknown as {
    status: string;
    ename?: string;
    evalue?: string;
  };
  if (content.status === 'error' || iopubErrors.length > 0) {
    const fallback = iopubErrors[0];
    const ename = content.ename ?? fallback?.ename ?? 'Error';
    const evalue = content.evalue ?? fallback?.evalue ?? 'kernel execution failed';
    throw new KernelExecuteError(ename, evalue);
  }
}

const plugin: JupyterFrontEndPlugin<void> = {
  id: 'longeron:launcher',
  description: 'Launcher tile that opens the Longeron model workbench.',
  autoStart: true,
  optional: [ILauncher, ICommandPalette, IConsoleTracker],
  activate: (
    app: JupyterFrontEnd,
    launcher: ILauncher | null,
    palette: ICommandPalette | null,
    consoles: IConsoleTracker | null
  ): void => {
    let current: IConsoleLike | null = null;
    let inFlight = false;

    const findRestoredConsole = (): IConsoleLike | null => {
      if (!consoles) {
        return null;
      }
      let found: IConsoleLike | null = null;
      consoles.forEach(panel => {
        if (!panel.isDisposed && panel.sessionContext.path === SESSION_PATH) {
          found = panel;
        }
      });
      return found;
    };

    const ensureConsole = async (): Promise<IConsoleLike> => {
      if (current && !current.isDisposed) {
        return current;
      }
      current = findRestoredConsole();
      if (current) {
        return current;
      }
      // `console:create` on the constant path either starts the session
      // or reconnects to a running one (SessionContext finds sessions by
      // path); the explicit default kernelspec skips the picker dialog.
      const specs = app.serviceManager.kernelspecs.specs;
      current = (await app.commands.execute('console:create', {
        path: SESSION_PATH,
        name: 'Longeron',
        activate: false,
        kernelPreference: { name: specs?.default ?? 'python3' }
      })) as IConsoleLike;
      return current;
    };

    const launch = async (): Promise<void> => {
      if (inFlight) {
        return; // a double-click must not race two kernel starts
      }
      inFlight = true;
      const toast = Notification.emit('Starting Longeron…', 'in-progress', {
        autoClose: false
      });
      try {
        const panel = await ensureConsole();
        await panel.sessionContext.ready;
        const kernel = panel.sessionContext.session?.kernel;
        if (!kernel) {
          throw new Error('the Longeron session has no kernel');
        }
        await executeOpen(kernel);
        Notification.update({
          id: toast,
          message: 'Longeron is ready — look for its tab in the left sidebar.',
          type: 'success',
          autoClose: 4000
        });
      } catch (reason) {
        current = null; // never pin a broken console; the next click retries
        const detail = reason instanceof Error ? reason.message : `${reason}`;
        Notification.update({
          id: toast,
          message: `Longeron failed to start: ${detail}`,
          type: 'error',
          autoClose: false
        });
      } finally {
        inFlight = false;
      }
    };

    app.commands.addCommand(COMMAND_ID, {
      label: 'Longeron',
      caption: 'Open the Longeron model workbench (no notebook needed)',
      icon: longeronIcon,
      execute: launch
    });
    if (launcher) {
      launcher.add({ command: COMMAND_ID, category: 'Other', rank: 1 });
    }
    if (palette) {
      palette.addItem({ command: COMMAND_ID, category: 'Longeron' });
    }
  }
};

export default plugin;
