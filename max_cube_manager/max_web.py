#!/usr/bin/env python3
"""Web interface for a MAX! Cube."""

from __future__ import annotations

import argparse
import json
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Sequence
from urllib.parse import unquote, urlsplit

if __package__:
    from .cube_api import CUBE_MESSAGE_API_PORT, CubeMessageAPIServer
    from .maxcube import CubeClient, CubeError, discover_cube, parse_schedule
else:
    from cube_api import CUBE_MESSAGE_API_PORT, CubeMessageAPIServer
    from maxcube import CubeClient, CubeError, discover_cube, parse_schedule


_LOGGER = logging.getLogger(__name__)


PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MAX! Cube</title>
<style>
:root{color-scheme:dark;--bg:#101820;--panel:#192630;--line:#314653;--text:#edf4f7;--muted:#a9bac4;--accent:#65d5c3;--warn:#ffb36b;--danger:#ff7777}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.45 system-ui,-apple-system,sans-serif}
header{padding:24px max(20px,calc((100vw - 1180px)/2));background:#14212a;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;align-items:center;gap:20px}
h1{font-size:23px;margin:0}h2{font-size:19px;margin:0 0 16px}h3{font-size:16px;margin:0 0 8px}.muted{color:var(--muted)}main{max-width:1180px;margin:auto;padding:22px}
nav{display:flex;gap:8px;margin:0 0 20px}.tab,button{border:1px solid var(--line);border-radius:8px;background:#21323e;color:var(--text);padding:9px 13px;cursor:pointer;font:inherit}
button:hover,.tab.active{border-color:var(--accent);color:var(--accent)}button.primary{background:#1e574f;border-color:#328f81}
input,select{background:#101a21;color:var(--text);border:1px solid var(--line);border-radius:7px;padding:8px 10px;font:inherit;min-width:0}
input:focus,select:focus,button:focus{outline:2px solid var(--accent);outline-offset:1px}
.panel,.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:18px;margin-bottom:16px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px}.row{display:flex;align-items:center;gap:9px;flex-wrap:wrap}.row input[type=text]{flex:1}
.device{border-top:1px solid var(--line);padding-top:12px;margin-top:12px}.device-meta{font-size:13px;color:var(--muted);margin:3px 0 9px}.room-devices{display:grid;gap:10px;margin-top:14px}.thermostat-card{padding:12px;border:1px solid var(--line);border-radius:9px}.thermostat-card h3{margin:0 0 4px}
.room-head,.thermostat-head{display:flex;justify-content:space-between;align-items:center;gap:12px}.menu{position:relative}.menu summary{list-style:none;border:1px solid var(--line);border-radius:8px;background:#21323e;padding:5px 11px;cursor:pointer;font-size:20px;line-height:1.2}.menu summary::-webkit-details-marker{display:none}.menu[open] .menu-content{position:absolute;z-index:5;right:calc(100% + 16px);top:0;width:min(290px,80vw);padding:14px;background:#14212a;border:1px solid var(--line);border-radius:10px;box-shadow:0 8px 24px #0008;display:grid;gap:10px}.menu-content input{width:100%}.temperature-row{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:6px 0}.temperature-label{color:var(--muted)}.setpoint-controls{display:flex;align-items:center;gap:6px}.setpoint-controls button{min-width:38px;padding:5px 10px;font-size:18px}.setpoint-controls button:disabled{opacity:.45;cursor:not-allowed}.thermostat-note{margin-top:5px}.room-setpoint{padding:8px 0;border-top:1px solid var(--line);margin-top:8px}
.form-row{display:flex;gap:10px;align-items:end;flex-wrap:wrap}.field{display:grid;gap:5px}.field label{font-size:13px;color:var(--muted)}
.status{min-height:24px;margin:8px 0;color:var(--accent)}.status.error{color:var(--danger)}.status.warn{color:var(--warn)}
.schedule-day{display:grid;grid-template-columns:54px minmax(180px,1fr) minmax(240px,1.3fr);gap:12px;align-items:center;border-top:1px solid var(--line);padding:12px 0}
.timeline{height:28px;display:flex;overflow:hidden;border-radius:6px;background:#27343d}.segment{height:100%;min-width:2px;display:flex;align-items:center;justify-content:center;overflow:hidden;color:#101820;font-size:11px;font-weight:650;white-space:nowrap}
.point-list{display:grid;gap:6px}.point{display:grid;grid-template-columns:1fr 1fr auto;gap:6px}.point input{width:100%}.point button{padding:5px 9px}
.schedule-head{display:flex;justify-content:space-between;align-items:end;gap:14px;flex-wrap:wrap}.notice{border-left:3px solid var(--warn);padding:8px 12px;color:var(--muted);background:#202b31}
.hidden{display:none!important}.nowrap{white-space:nowrap}.small{font-size:12px;color:var(--muted)}
@media(max-width:760px){header{align-items:flex-start;flex-direction:column}.schedule-day{grid-template-columns:42px 1fr}.point-list{grid-column:1/-1}}
</style>
</head>
<body>
<header><div><h1>MAX! Cube</h1><div class="muted" id="cube-status">Connecting…</div></div><button id="refresh">Refresh</button></header>
<main>
<div id="global-status" class="status" role="status" aria-live="polite"></div>
<section id="devices-view">
 <div class="panel">
  <h2>Thermostats by room</h2>
  <div id="rooms" class="grid"></div>
 </div>
</section>
<section id="schedule-view" class="hidden">
 <div class="panel">
  <div class="schedule-head">
   <div><button id="back-to-rooms">Back to rooms</button><h2 style="margin-top:12px">Weekly schedule</h2><div class="muted">Each temperature runs until its listed time; the final entry runs through midnight.</div></div>
   <div class="field"><label for="target-device">Thermostat</label><select id="target-device"></select></div>
  </div>
  <div id="schedule-empty" class="muted hidden">No thermostats found.</div>
  <div id="schedule-notice" class="notice hidden"></div>
  <div id="schedule-days" style="margin-top:16px"></div>
  <div class="row" style="justify-content:space-between;margin-top:14px">
   <span class="small">Times use 24-hour format in 5-minute increments; temperatures use 0.5°C increments.</span>
   <button id="apply-schedule" class="primary">Save schedule</button>
  </div>
 </div>
</section>
</main>
<script>
const DAYS=["Sa","Su","Mo","Tu","We","Th","Fr"];
let state={rooms:[],thermostats:[]}, schedule={}, scheduleAddress="", busyRooms=new Set();
const $=id=>document.getElementById(id);
function setStatus(message,error=false,warn=false){const node=$("global-status");node.textContent=message;node.className="status"+(error?" error":warn?" warn":"")}
async function api(path,options={}){const requestUrl=new URL(path.replace(/^\/+/,""),document.baseURI);let response;try{response=await fetch(requestUrl,{...options,headers:{"Content-Type":"application/json",...(options.headers||{})}})}catch(error){throw new Error(`${requestUrl.pathname}: ${error.message}`)}const contentType=response.headers.get("Content-Type")||"unknown";let data;try{data=await response.json()}catch{throw new Error(`${requestUrl.pathname} returned non-JSON response (HTTP ${response.status}, content type ${contentType})`)}if(!response.ok)throw new Error(data.error||`${requestUrl.pathname} failed with HTTP ${response.status}`);return data}
function button(text,action,kind=""){const node=document.createElement("button");node.type="button";node.textContent=text;if(kind)node.className=kind;node.addEventListener("click",action);return node}
function addOption(select,value,label){const option=document.createElement("option");option.value=value;option.textContent=label;select.append(option)}
function targetTemperature(device){const value=device.status?.target_temperature;return typeof value==="number"&&Number.isFinite(value)&&value>0?value:null}
function roomTemperature(devices){const ordered=[...devices].sort((a,b)=>(b.type_code===3?1:0)-(a.type_code===3?1:0));for(const device of ordered){const value=targetTemperature(device);if(value!==null)return value}return null}
function roomLimits(devices){return{minimum:Math.max(...devices.map(device=>Number(device["minimum temperature"]??4.5))),maximum:Math.min(...devices.map(device=>Number(device["maximum temperature"]??30.5)))}}
function temperatureText(value){return typeof value==="number"&&Number.isFinite(value)?`${value.toFixed(1)}°C`:"Not reported"}
function changeButtons(roomId,target,devices,path){const controls=document.createElement("div");controls.className="setpoint-controls";const limits=roomLimits(devices);for(const [delta,label] of [[-0.5,"Decrease target temperature"],[0.5,"Increase target temperature"]]){const control=button(delta<0?"−":"+",()=>changeSetpoint(roomId,path,delta));control.setAttribute("aria-label",label);control.disabled=!roomId||target===null||busyRooms.has(roomId)||target+delta<limits.minimum||target+delta>limits.maximum;control.dataset.roomId=String(roomId);controls.append(control)}return controls}
function optionsMenu(label){const details=document.createElement("details");details.className="menu";const summary=document.createElement("summary");summary.textContent="☰";summary.setAttribute("aria-label",`${label} options`);details.append(summary);const content=document.createElement("div");content.className="menu-content";details.append(content);details.addEventListener("toggle",()=>{if(details.open)for(const other of document.querySelectorAll("details.menu[open]"))if(other!==details)other.open=false});return{details,content}}
function renderThermostat(device){const card=document.createElement("article");card.className="thermostat-card";const head=document.createElement("div");head.className="thermostat-head";const heading=document.createElement("h3");heading.textContent=device.name||device.type||"Thermostat";head.append(heading);const menu=optionsMenu(`Thermostat ${device.address}`);const nameLabel=document.createElement("label");nameLabel.textContent="Thermostat name";const name=document.createElement("input");name.maxLength=32;name.value=device.name||"";name.setAttribute("aria-label",`Thermostat ${device.address} name`);name.placeholder="Thermostat name";const roomLabel=document.createElement("label");roomLabel.className="small";roomLabel.textContent="Room";const select=document.createElement("select");select.setAttribute("aria-label",`Room for thermostat ${device.address}`);addOption(select,"0","Unassigned");for(const item of state.rooms)addOption(select,item.id,item.name||`Room ${item.id}`);select.value=String(device.room_id||0);menu.content.append(nameLabel,name,button("Save name",()=>mutate(`/api/thermostats/${device.address}`,"PATCH",{name:name.value})),roomLabel,select,button("Move",()=>mutate(`/api/thermostats/${device.address}`,"PATCH",{room_id:Number(select.value)})),button("View / edit schedule",()=>openSchedule(device.address)));head.append(menu.details);card.append(head);const meta=document.createElement("div");meta.className="device-meta";meta.textContent=`${device.address} · ${device.serial||"serial unavailable"}`;card.append(meta);
 const room=state.rooms.find(item=>item.id===device.room_id),members=room?state.thermostats.filter(item=>item.room_id===room.id):[],target=targetTemperature(device);const currentRow=document.createElement("div");currentRow.className="temperature-row";const currentLabel=document.createElement("span");currentLabel.className="temperature-label";currentLabel.textContent="Current";const currentValue=document.createElement("strong");currentValue.textContent=temperatureText(device.status?.current_temperature);currentRow.append(currentLabel,currentValue);card.append(currentRow);const targetRow=document.createElement("div");targetRow.className="temperature-row";const targetLabel=document.createElement("span");targetLabel.className="temperature-label";targetLabel.textContent="Target";const targetValue=document.createElement("strong");targetValue.textContent=temperatureText(target);targetRow.append(targetLabel,targetValue,changeButtons(device.room_id||0,target,members,`/api/thermostats/${device.address}/setpoint`));card.append(targetRow);const note=document.createElement("div");note.className="small thermostat-note";note.textContent=room?`Manual target controls affect all thermostats in ${room.name||`Room ${room.id}`}.`:"Assign this thermostat to a room to adjust its target.";card.append(note);
 return card}
function render(){const roomBox=$("rooms"),targetDevice=$("target-device");roomBox.replaceChildren();const selectedAddress=targetDevice.value||scheduleAddress;targetDevice.replaceChildren();
 for(const device of state.thermostats)addOption(targetDevice,device.address,`${device.name||device.address} · ${device.address}`);
 if(state.thermostats.some(device=>device.address===selectedAddress))targetDevice.value=selectedAddress;
 for(const room of state.rooms){const members=state.thermostats.filter(device=>device.room_id===room.id);const card=document.createElement("article");card.className="card";const head=document.createElement("div");head.className="room-head";const heading=document.createElement("h3");heading.textContent=room.name||`Room ${room.id}`;head.append(heading);const menu=optionsMenu(`Room ${room.id}`);const nameLabel=document.createElement("label");nameLabel.textContent="Room name";const name=document.createElement("input");name.maxLength=32;name.value=room.name||"";name.placeholder="Room name";name.setAttribute("aria-label",`Room ${room.id} name`);menu.content.append(nameLabel,name,button("Save name",()=>mutate(`/api/rooms/${room.id}`,"PATCH",{name:name.value})));head.append(menu.details);card.append(head);const roomTarget=roomTemperature(members);const roomSetpoint=document.createElement("div");roomSetpoint.className="room-setpoint";const roomTargetRow=document.createElement("div");roomTargetRow.className="temperature-row";const roomTargetLabel=document.createElement("span");roomTargetLabel.className="temperature-label";roomTargetLabel.textContent="Room target";const roomTargetValue=document.createElement("strong");roomTargetValue.textContent=temperatureText(roomTarget);roomTargetRow.append(roomTargetLabel,roomTargetValue,changeButtons(room.id,roomTarget,members,`/api/rooms/${room.id}/setpoint`));roomSetpoint.append(roomTargetRow);const roomNote=document.createElement("div");roomNote.className="small";roomNote.textContent="Manual adjustment changes the target for all thermostats in this room; schedules remain separate.";roomSetpoint.append(roomNote);card.append(roomSetpoint);const devices=document.createElement("div");devices.className="room-devices";for(const device of members)devices.append(renderThermostat(device));if(!devices.childElementCount){const empty=document.createElement("div");empty.className="muted";empty.textContent="No thermostats in this room.";devices.append(empty)}card.append(devices);roomBox.append(card)}
 const unassigned=state.thermostats.filter(device=>!state.rooms.some(room=>room.id===device.room_id));if(unassigned.length){const card=document.createElement("article");card.className="card";const heading=document.createElement("h3");heading.textContent="Unassigned thermostats";card.append(heading);const devices=document.createElement("div");devices.className="room-devices";for(const device of unassigned)devices.append(renderThermostat(device));card.append(devices);roomBox.append(card)}
 if(!state.rooms.length&&!unassigned.length){const empty=document.createElement("p");empty.className="muted";empty.textContent="No thermostats found.";roomBox.append(empty)}
 $("cube-status").textContent=`Cube ${state.cube?.serial||""} · ${state.host||""}`;
 $("schedule-empty").classList.toggle("hidden",state.thermostats.length>0);$("apply-schedule").disabled=state.thermostats.length===0;$("schedule-days").classList.toggle("hidden",state.thermostats.length===0);
}
async function refresh(reloadSchedule=false){try{state=await api("/api/state");render();const selectedAddress=$("target-device").value;if(selectedAddress&&((reloadSchedule)||scheduleAddress!==selectedAddress))loadDeviceSchedule(selectedAddress);$("cube-status").textContent=`Cube ${state.cube?.serial||""} · ${state.host||""}`;setStatus("Connected to Cube.")}catch(error){$("cube-status").textContent=`Connection failed · ${error.message}`;setStatus(`Could not load Cube state: ${error.message}`,true)}}
async function mutate(path,method,body){try{setStatus("Working…");const result=await api(path,{method,body:JSON.stringify(body)});setStatus(result.message||"Done.");await refresh()}catch(error){setStatus(error.message,true)}}
async function changeSetpoint(roomId,path,delta){if(busyRooms.has(roomId))return;busyRooms.add(roomId);render();try{const result=await api(path,{method:"POST",body:JSON.stringify({delta})});await refresh(true);setStatus(result.message)}catch(error){setStatus(error.message,true)}finally{busyRooms.delete(roomId);render()}}
function showTab(name){$("devices-view").classList.toggle("hidden",name!=="devices");$("schedule-view").classList.toggle("hidden",name!=="schedule")}
function openSchedule(address){$("target-device").value=address;loadDeviceSchedule(address);showTab("schedule")}
$("back-to-rooms").addEventListener("click",()=>showTab("devices"));
$("refresh").addEventListener("click",()=>refresh(true));
function formatTime(seconds){if(seconds>=86400)return"24:00";const h=Math.floor(seconds/3600),m=Math.floor(seconds%3600/60);return`${String(h).padStart(2,"0")}:${String(m).padStart(2,"0")}`}
function parseTime(value){const match=/^(\d{1,2}):([0-5]\d)$/.exec(value);if(!match)throw new Error("Use HH:MM for schedule times.");const h=Number(match[1]),m=Number(match[2]);if(h>24||(h===24&&m!==0))throw new Error("Schedule times must be before 24:00.");if(m%5!==0)throw new Error("Schedule times must be in five-minute increments.");return(h*60+m)*60}
function loadDeviceSchedule(address){scheduleAddress=address;const device=state.thermostats.find(item=>item.address===address);const missingDays=DAYS.filter(day=>!Array.isArray(device?.schedule?.[day])||!device.schedule[day].length);schedule=Object.fromEntries(DAYS.map(day=>[day,structuredClone(device?.schedule?.[day]||[])]));renderSchedule();$("apply-schedule").disabled=!device;$("schedule-empty").classList.toggle("hidden",Boolean(device));$("schedule-notice").textContent=missingDays.length?`No current schedule data for: ${missingDays.join(", ")}. Add transitions before saving.`:"";$("schedule-notice").classList.toggle("hidden",!device||!missingDays.length);$("schedule-days").classList.toggle("hidden",!device)}
function renderTimeline(day,container,points){container.replaceChildren();let start=0;for(const point of points){const end=Math.max(start,Math.min(86400,Number(point.time)));const segment=document.createElement("div");segment.className="segment";segment.style.flex=`${Math.max(end-start,1)} 0 0`;const temp=Number(point.temperature);const hue=Math.max(0,Math.min(210,210-(temp-10)*12));segment.style.background=`hsl(${hue} 72% 67%)`;segment.title=`${formatTime(start)}–${formatTime(end)} · ${temp.toFixed(1)}°C`;segment.textContent=`${temp.toFixed(1)}°`;container.append(segment);start=end}if(start<86400){const tail=document.createElement("div");tail.className="segment";tail.style.flex=`${86400-start} 0 0`;tail.style.background="#354651";tail.title=`${formatTime(start)}–24:00`;container.append(tail)}}
function updateDayFromInputs(day,card){try{const points=[];for(const row of card.querySelectorAll(".point"))points.push({time:parseTime(row.querySelector(".point-time").value),temperature:Number(row.querySelector(".point-temp").value)});points.sort((a,b)=>a.time-b.time);schedule[day]=points;renderTimeline(day,card.querySelector(".timeline"),points);return true}catch(error){setStatus(error.message,true);return false}}
function addPointRow(day,card,point){const list=card.querySelector(".point-list"),row=document.createElement("div");row.className="point";const time=document.createElement("input");time.type="text";time.inputMode="numeric";time.placeholder="HH:MM";time.className="point-time";time.value=formatTime(point.time);time.setAttribute("aria-label",`${day} end time`);const temp=document.createElement("input");temp.type="number";temp.min="0.5";temp.max="31.5";temp.step="0.5";temp.className="point-temp";temp.value=point.temperature;temp.setAttribute("aria-label",`${day} temperature`);row.append(time,temp,button("×",()=>{row.remove();updateDayFromInputs(day,card)},"danger"));for(const input of [time,temp])input.addEventListener("change",()=>updateDayFromInputs(day,card));list.append(row)}
function renderSchedule(){const root=$("schedule-days");root.replaceChildren();for(const day of DAYS){const card=document.createElement("div");card.className="schedule-day";const label=document.createElement("strong");label.textContent=day;const timeline=document.createElement("div");timeline.className="timeline";const list=document.createElement("div");list.className="point-list";const controls=document.createElement("div");controls.className="row";controls.append(button("+ transition",()=>{const points=schedule[day]||[];points.push({time:43200,temperature:20});schedule[day]=points;addPointRow(day,card,points[points.length-1]);updateDayFromInputs(day,card)}));card.append(label,timeline,list,controls);for(const point of schedule[day]||[])addPointRow(day,card,point);renderTimeline(day,timeline,schedule[day]||[]);root.append(card)}}
$("target-device").addEventListener("change",()=>loadDeviceSchedule($("target-device").value));
$("apply-schedule").addEventListener("click",async()=>{try{for(const day of DAYS){const card=[...$("schedule-days").children].find(item=>item.firstChild.textContent===day);if(!updateDayFromInputs(day,card))return;if(!schedule[day]?.length)throw new Error(`${day} needs at least one transition.`)}const address=$("target-device").value;if(!address)throw new Error("Select a thermostat first.");setStatus("Saving thermostat schedule…");const result=await api("/api/schedules/apply",{method:"POST",body:JSON.stringify({address,schedule})});setStatus(result.message||`Schedule saved for ${address}.`);await refresh(true)}catch(error){setStatus(error.message,true)}});
refresh();
</script>
</body>
</html>"""


class CubeWebServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        address,
        handler,
        cube_host: str,
        cube_port: int,
        allow_home_assistant_ingress: bool = False,
        debug: bool = False,
    ) -> None:
        super().__init__(address, handler)
        self.cube_host = cube_host
        self.cube_port = cube_port
        self.allow_home_assistant_ingress = allow_home_assistant_ingress
        self.debug = debug
        self.cube_lock = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    server: CubeWebServer

    def _send_json(self, status: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _send_page(self) -> None:
        body = PAGE.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _check_origin(self) -> bool:
        host_header = self.headers.get("Host", "")
        host = urlsplit("//" + host_header).hostname
        if self.server.allow_home_assistant_ingress:
            if self.client_address[0] != "172.30.32.2":
                self._send_json(
                    403,
                    {"error": "Only Home Assistant ingress requests are allowed"},
                )
                return False
            if not host:
                self._send_json(403, {"error": "A valid Host header is required"})
                return False
            origin = self.headers.get("Origin")
            if origin:
                origin_parts = urlsplit(origin)
                if (
                    origin_parts.scheme not in {"http", "https"}
                    or origin_parts.netloc.lower() != host_header.lower()
                ):
                    self._send_json(403, {"error": "Cross-origin requests are not allowed"})
                    return False
            return True

        if host not in {"127.0.0.1", "localhost"}:
            self._send_json(403, {"error": "Only localhost requests are allowed"})
            return False
        origin = self.headers.get("Origin")
        if origin:
            origin_host = urlsplit(origin).hostname
            if origin_host not in {"127.0.0.1", "localhost"}:
                self._send_json(403, {"error": "Cross-origin requests are not allowed"})
                return False
        return True

    def _read_json(self) -> Dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("Invalid Content-Length") from exc
        if length < 0 or length > 131072:
            raise ValueError("Request body must be at most 128 KiB")
        if self.headers.get_content_type() != "application/json":
            raise ValueError("Request body must use application/json")
        try:
            data = json.loads(self.rfile.read(length))
        except json.JSONDecodeError as exc:
            raise ValueError("Request body must contain valid JSON") from exc
        if not isinstance(data, dict):
            raise ValueError("Request body must be a JSON object")
        return data

    def _with_cube(self, callback):
        action = f"{self.command} {urlsplit(getattr(self, 'path', '')).path or 'request'}"
        started = time.monotonic()
        if self.server.debug:
            _LOGGER.debug(
                "Connecting to MAX! Cube %s:%d for %s",
                self.server.cube_host,
                self.server.cube_port,
                action,
            )
        with self.server.cube_lock:
            try:
                with CubeClient(self.server.cube_host, self.server.cube_port) as cube:
                    result = callback(cube)
            except (CubeError, OSError):
                if self.server.debug:
                    _LOGGER.debug(
                        "MAX! Cube operation %s failed after %.3f seconds",
                        action,
                        time.monotonic() - started,
                        exc_info=True,
                    )
                raise
        if self.server.debug:
            _LOGGER.debug(
                "MAX! Cube operation %s completed in %.3f seconds",
                action,
                time.monotonic() - started,
            )
        return result

    def do_GET(self) -> None:
        if not self._check_origin():
            return
        path = urlsplit(self.path).path
        if path == "/":
            self._send_page()
            return
        if path == "/api/state":
            try:
                snapshot = self._with_cube(lambda cube: cube.snapshot())
                snapshot["host"] = self.server.cube_host
                self._send_json(200, snapshot)
            except (CubeError, OSError) as exc:
                self._send_json(502, {"error": str(exc)})
            return
        self._send_json(404, {"error": "Not found"})

    def do_POST(self) -> None:
        self._mutate()

    def do_PATCH(self) -> None:
        self._mutate()

    def _mutate(self) -> None:
        if not self._check_origin():
            return
        path = unquote(urlsplit(self.path).path)
        try:
            data = self._read_json()
            result = self._route_mutation(path, data)
            self._send_json(200, result)
        except (CubeError, ValueError, KeyError) as exc:
            if self.server.debug and not isinstance(exc, CubeError):
                _LOGGER.debug(
                    "Rejected %s %s: %s",
                    self.command,
                    path,
                    exc,
                )
            self._send_json(400, {"error": str(exc)})
        except OSError as exc:
            self._send_json(502, {"error": str(exc)})

    def _route_mutation(self, path: str, data: Dict[str, Any]) -> Dict[str, Any]:
        parts = path.strip("/").split("/")
        if self.command == "POST" and len(parts) == 4 and parts[:2] == ["api", "rooms"] and parts[3] == "setpoint":
            room_id = int(parts[2])
            result = self._with_cube(
                lambda cube: cube.adjust_room_setpoint(room_id, data.get("delta"))
            )
            return {
                **result,
                "message": (
                    f"Room {room_id} target set to {result['temperature']:.1f}°C; "
                    f"affects all {len(result['thermostats'])} thermostat(s)."
                ),
            }

        if self.command == "POST" and len(parts) == 4 and parts[:2] == ["api", "thermostats"] and parts[3] == "setpoint":
            address = parts[2].upper()
            def adjust_thermostat_room(cube):
                device = cube.devices.get(address)
                if device is None or device.get("type_code") not in {1, 2, 3}:
                    raise CubeError(f"Thermostat {address} does not exist")
                room_id = int(device.get("room_id", 0))
                return cube.adjust_room_setpoint(room_id, data.get("delta"), address=address)
            result = self._with_cube(adjust_thermostat_room)
            return {
                **result,
                "message": (
                    f"Room {result['room_id']} target set to {result['temperature']:.1f}°C; "
                    f"affects all {len(result['thermostats'])} thermostat(s)."
                ),
            }

        if len(parts) == 3 and parts[:2] == ["api", "rooms"]:
            room_id = int(parts[2])
            if self.command == "PATCH":
                room = self._with_cube(lambda cube: cube.rename_room(room_id, data.get("name", "")))
                return {"room": room, "message": f"Room {room_id} renamed"}

        if len(parts) == 3 and parts[:2] == ["api", "thermostats"]:
            address = parts[2].upper()
            if self.command == "PATCH":
                def update(cube):
                    if "room_id" in data:
                        cube.assign_thermostat(address, int(data["room_id"]))
                    if "name" in data:
                        return cube.rename_thermostat(address, data["name"])
                    device = cube.devices.get(address)
                    if device is None:
                        raise CubeError(f"Thermostat {address} does not exist")
                    return device
                thermostat = self._with_cube(update)
                return {"thermostat": thermostat, "message": f"Thermostat {address} updated"}

        if self.command == "POST" and path == "/api/schedules/apply":
            address = data.get("address")
            if not isinstance(address, str) or not address:
                raise ValueError("A thermostat address is required")
            schedule = parse_schedule(data.get("schedule", {}))
            self._with_cube(lambda cube: cube.set_schedule(address, schedule))
            return {"address": address.upper(), "message": f"Schedule saved for {address.upper()}"}

        raise ValueError("Unknown web action")

    def log_message(self, format_string: str, *args: Any) -> None:
        super().log_message(format_string, *args)
        if self.server.debug:
            _LOGGER.debug(
                "HTTP request details: client=%s method=%s path=%s content_type=%s content_length=%s",
                self.client_address[0],
                self.command,
                urlsplit(self.path).path,
                self.headers.get("Content-Type", "-"),
                self.headers.get("Content-Length", "-"),
            )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the MAX! Cube web interface.")
    parser.add_argument(
        "--cube-host",
        help="MAX! Cube host or IPv4 address; auto-discovered by default",
    )
    parser.add_argument("--cube-port", type=int, default=62910)
    parser.add_argument("--bind", default="127.0.0.1", help="Web bind address")
    parser.add_argument("--port", type=int, default=8765, help="Web server port")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Log detailed HTTP and MAX! Cube diagnostics",
    )
    parser.add_argument(
        "--home-assistant-ingress",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.bind not in {"127.0.0.1", "localhost"} and not (
        args.home_assistant_ingress and args.bind == "0.0.0.0"
    ):
        parser.error("Non-loopback bind addresses are only allowed for Home Assistant ingress")

    server = None
    message_api_server = None
    try:
        cube_host = args.cube_host or discover_cube()[0]
        server = CubeWebServer(
            (args.bind, args.port),
            Handler,
            cube_host,
            args.cube_port,
            allow_home_assistant_ingress=args.home_assistant_ingress,
            debug=args.debug,
        )
        if args.home_assistant_ingress:
            message_api_server = CubeMessageAPIServer(
                ("0.0.0.0", CUBE_MESSAGE_API_PORT),
                cube_host,
                args.cube_port,
                server.cube_lock,
                debug=args.debug,
            )
    except (CubeError, OSError) as exc:
        if message_api_server is not None:
            message_api_server.server_close()
        if server is not None:
            server.server_close()
        print(f"ERROR: {exc}")
        return 1

    access = (
        "Home Assistant ingress"
        if args.home_assistant_ingress
        else f"http://{args.bind}:{server.server_port}/"
    )
    print(f"MAX! Cube {cube_host}; web UI at {access}")
    api_thread = None
    try:
        if message_api_server is not None:
            api_thread = threading.Thread(
                target=message_api_server.serve_forever,
                name="cube-message-api",
                daemon=True,
            )
            api_thread.start()
            _LOGGER.info(
                "Internal Cube message API listening on port %d",
                CUBE_MESSAGE_API_PORT,
            )
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping MAX! Cube web server")
    finally:
        if message_api_server is not None:
            if api_thread is not None and api_thread.is_alive():
                message_api_server.shutdown()
                api_thread.join()
            message_api_server.server_close()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
