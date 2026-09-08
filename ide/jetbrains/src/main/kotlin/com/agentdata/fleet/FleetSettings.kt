package com.agentdata.fleet

import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.components.PersistentStateComponent
import com.intellij.openapi.components.Service
import com.intellij.openapi.components.State
import com.intellij.openapi.components.Storage

/**
 * Port and command, and nothing else.
 *
 * There is deliberately no settings UI: every other choice the fleet offers -- what an agent may
 * run, when to notify, which JQL to show -- is `ad-setup` and the config file's, and duplicating
 * any of it here would give the operator two places to set one thing.
 */
@Service(Service.Level.APP)
@State(name = "AgentdataFleet", storages = [Storage("agentdata-fleet.xml")])
class FleetSettings : PersistentStateComponent<FleetSettings.State> {

    data class State(
        var port: Int = 8765,
        var command: String = ""
    )

    private var state = State()

    val port: Int get() = state.port
    val command: String get() = state.command

    override fun getState(): State = state

    override fun loadState(loaded: State) {
        state = loaded
    }

    companion object {
        fun getInstance(): FleetSettings =
            ApplicationManager.getApplication().getService(FleetSettings::class.java)
    }
}
