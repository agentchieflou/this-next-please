package com.agentdata.fleet

import com.intellij.openapi.actionSystem.AnAction
import com.intellij.openapi.actionSystem.AnActionEvent
import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.project.DumbAware
import com.intellij.openapi.ui.Messages

/**
 * "Start a fleet agent on this project" -- the common case, which is this project and one ticket.
 *
 * It refuses nothing itself. The key's shape is checked because a typo here costs a round trip,
 * but every real rule -- wrong project, live agent, finished ticket -- belongs to `ad-fleet start`
 * and comes back as its own words.
 */
class StartHereAction : AnAction("Start a Fleet Agent on This Project…"), DumbAware {

    override fun actionPerformed(e: AnActionEvent) {
        val project = e.project ?: return
        val record = Fleet.running()
        if (record == null) {
            Messages.showWarningDialog(
                project,
                "No fleet dashboard is running. Open the Fleet tool window, or run `ad-fleet serve`.",
                "Fleet"
            )
            return
        }

        val here = project.basePath?.replace('\', '/')?.lowercase()
        val known = Fleet.repos(record)
        val mine = known.firstOrNull { it.second.replace('\', '/').lowercase() == here }
        if (mine == null) {
            Messages.showWarningDialog(
                project,
                "This project is not a registered fleet repository.\n\n" +
                    "Register it with:  ad-fleet repo add ${project.basePath ?: "<path>"}",
                "Fleet"
            )
            return
        }

        val ticket = Messages.showInputDialog(
            project, "Ticket key to work in ${mine.first}", "Fleet", null, "", object : com.intellij.openapi.ui.InputValidator {
                override fun checkInput(input: String?): Boolean =
                    input != null && Regex("^[A-Za-z][A-Za-z0-9_]+-\d+$").matches(input.trim())

                override fun canClose(input: String?): Boolean = checkInput(input)
            }
        )?.trim()?.uppercase() ?: return

        ApplicationManager.getApplication().executeOnPooledThread {
            val (ok, detail) = Fleet.startAgent(record, mine.first, ticket)
            ApplicationManager.getApplication().invokeLater {
                if (ok) {
                    Messages.showInfoMessage(project, "$ticket started in ${mine.first}.", "Fleet")
                } else {
                    Messages.showWarningDialog(project, detail, "Fleet")
                }
            }
        }
    }
}
