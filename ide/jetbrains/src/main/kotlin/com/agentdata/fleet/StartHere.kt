package com.agentdata.fleet

import com.intellij.openapi.actionSystem.AnAction
import com.intellij.openapi.actionSystem.AnActionEvent
import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.project.DumbAware
import com.intellij.openapi.ui.InputValidator
import com.intellij.openapi.ui.Messages

/**
 * "Start a fleet agent on this project" -- the common case, which is this project and one ticket.
 *
 * It refuses nothing itself. The key's shape is checked because a typo here costs a round trip,
 * but every real rule -- wrong project, live agent, finished ticket -- belongs to `ad-fleet start`
 * and comes back in its own words.
 */
class StartHereAction : AnAction("Start a Fleet Agent on This Project…"), DumbAware {

    private val keyShape = Regex("^[A-Za-z][A-Za-z0-9_]+-[0-9]+$")

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

        val here = normalize(project.basePath)
        val known = Fleet.repos(record)
        val mine = known.firstOrNull { normalize(it.second) == here }
        if (mine == null) {
            Messages.showWarningDialog(
                project,
                "This project is not a registered fleet repository.\n\n" +
                    "Register it with:  ad-fleet repo add " + (project.basePath ?: "<path>"),
                "Fleet"
            )
            return
        }

        val validator = object : InputValidator {
            override fun checkInput(input: String?): Boolean =
                input != null && keyShape.matches(input.trim())

            override fun canClose(input: String?): Boolean = checkInput(input)
        }
        val ticket = Messages
            .showInputDialog(project, "Ticket key to work in " + mine.first, "Fleet", null, "", validator)
            ?.trim()?.uppercase() ?: return

        ApplicationManager.getApplication().executeOnPooledThread {
            val answer = Fleet.startAgent(record, mine.first, ticket)
            ApplicationManager.getApplication().invokeLater {
                if (answer.first) {
                    Messages.showInfoMessage(project, ticket + " started in " + mine.first + ".", "Fleet")
                } else {
                    Messages.showWarningDialog(project, answer.second, "Fleet")
                }
            }
        }
    }

    /** One spelling for a path, so a Windows checkout compares equal to what the fleet recorded. */
    private fun normalize(path: String?): String =
        (path ?: "").replace('\\', '/').trimEnd('/').lowercase()
}
