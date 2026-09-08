package com.agentdata.fleet

import com.intellij.notification.NotificationGroupManager
import com.intellij.notification.NotificationType
import com.intellij.openapi.actionSystem.AnAction
import com.intellij.openapi.actionSystem.AnActionEvent
import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.project.DumbAware
import com.intellij.openapi.project.Project
import com.intellij.openapi.ui.Messages
import com.intellij.openapi.wm.ToolWindow
import com.intellij.openapi.wm.ToolWindowFactory
import com.intellij.ui.components.JBLabel
import com.intellij.ui.jcef.JBCefApp
import com.intellij.ui.jcef.JBCefBrowser
import com.intellij.util.ui.JBUI
import java.awt.BorderLayout
import javax.swing.JPanel

/**
 * A tool window that hosts the dashboard, and nothing else.
 *
 * No UI of its own beyond a toolbar with two buttons: everything a person does here is done by the
 * page (#96), which is the same page VS Code shows and the same page on the fourth monitor. A
 * second UI would be a second thing to keep in step with the server.
 */
class FleetToolWindowFactory : ToolWindowFactory, DumbAware {

    override fun createToolWindowContent(project: Project, toolWindow: ToolWindow) {
        val panel = FleetPanel(project)
        val content = toolWindow.contentManager.factory.createContent(panel, "", false)
        content.setDisposer(panel)
        toolWindow.contentManager.addContent(content)
        toolWindow.setTitleActions(listOf(panel.reloadAction(), panel.browserAction()))
    }
}

class FleetPanel(private val project: Project) : JPanel(BorderLayout()), com.intellij.openapi.Disposable {

    private var browser: JBCefBrowser? = null
    private var notifications: Fleet.Notifications? = null

    init {
        if (!JBCefApp.isSupported()) {
            // Said plainly rather than shown as an empty panel: a blank tool window reads as a
            // broken plugin, and the actual answer -- use the browser -- is one sentence.
            add(
                JBLabel(
                    "<html><p>This IDE was started without JCEF, so the dashboard cannot be embedded.</p>" +
                        "<p>Run <code>ad-fleet open</code> to see it in a browser. " +
                        "Help &rarr; About shows the runtime; a JetBrains Runtime with JCEF fixes this.</p></html>"
                ).apply { border = JBUI.Borders.empty(12) },
                BorderLayout.NORTH
            )
        } else {
            val view = JBCefBrowser()
            browser = view
            add(view.component, BorderLayout.CENTER)
            ApplicationManager.getApplication().executeOnPooledThread { connect() }
        }
    }

    /** Attach to a running dashboard, starting one if there is none, then show it. */
    private fun connect() {
        val settings = FleetSettings.getInstance()
        val record = try {
            Fleet.running() ?: Fleet.startServer(settings.port, settings.command)
        } catch (e: Exception) {
            balloon("The fleet dashboard is not running", e.message ?: "", NotificationType.WARNING)
            return
        }
        show(record.url)
        warnOnContractMismatch(record)

        notifications?.stop()
        val stream = Fleet.Notifications(record) { note -> onNote(note) }
        notifications = stream
        ApplicationManager.getApplication().executeOnPooledThread(stream)
    }

    private fun show(url: String) {
        ApplicationManager.getApplication().invokeLater { browser?.loadURL(url) }
    }

    /**
     * One balloon when the shell and the server are different ages, and never a second for the
     * same pair. A shell built against an older contract mis-renders quietly, which is the kind of
     * bug that gets blamed on the dashboard for a week.
     */
    private var warnedAbout = ""

    private fun warnOnContractMismatch(record: Fleet.Record) {
        val answer = Fleet.ping(record.port) ?: return
        if (answer.contract == Fleet.CONTRACT || warnedAbout == answer.version) return
        warnedAbout = answer.version
        balloon(
            "The fleet dashboard and this plugin are different ages",
            "The dashboard speaks contract ${answer.contract} and this plugin speaks ${Fleet.CONTRACT}. " +
                "Update with `ad-update`, and the plugin from the release it came from.",
            NotificationType.WARNING
        )
    }

    private fun onNote(note: Fleet.Note) {
        if (note.severity == "info") return
        val type = if (note.severity == "alert") NotificationType.ERROR else NotificationType.WARNING
        val notification = NotificationGroupManager.getInstance()
            .getNotificationGroup("agentdata.fleet")
            .createNotification(note.title, note.body, type)
        notification.addAction(object : AnAction("Show") {
            override fun actionPerformed(e: AnActionEvent) {
                // `#tile=<repo>` is the whole vocabulary for "show me that one" -- the same anchor
                // the Windows toasts use, so there is one way to focus a tile and not two.
                Fleet.running()?.let { show("${it.url}#tile=${note.repo}") }
                notification.expire()
            }
        })
        notification.notify(project)
    }

    private fun balloon(title: String, body: String, type: NotificationType) {
        NotificationGroupManager.getInstance()
            .getNotificationGroup("agentdata.fleet")
            .createNotification(title, body, type)
            .notify(project)
    }

    fun reloadAction(): AnAction = object : AnAction("Reload", "Reconnect to the fleet dashboard", null) {
        override fun actionPerformed(e: AnActionEvent) {
            ApplicationManager.getApplication().executeOnPooledThread { connect() }
        }
    }

    fun browserAction(): AnAction = object : AnAction("Open in Browser", "Show the dashboard outside the IDE", null) {
        override fun actionPerformed(e: AnActionEvent) {
            val record = Fleet.running()
            if (record == null) {
                Messages.showInfoMessage(project, "No fleet dashboard is running.", "Fleet")
                return
            }
            com.intellij.ide.BrowserUtil.browse(record.url)
        }
    }

    override fun dispose() {
        notifications?.stop()
        browser?.let { com.intellij.openapi.util.Disposer.dispose(it) }
    }
}
