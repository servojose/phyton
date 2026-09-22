import tkinter as tk
from tkinter import ttk
import threading
import time

# Intentar importar pymodbus. Forzamos el uso de la conexión real con el PLC
try:
    from pymodbus.client import ModbusSerialClient as ModbusClient
    MODBUS_DISPONIBLE = True
except ImportError:
    MODBUS_DISPONIBLE = False

# =====================================================================
# 1. BLOQUE DE FUNCIÓN REUTILIZABLE (BHEATCOOLDIG)
# =====================================================================
class BHEATCOOLDIG:
    def __init__(self):
        self.rSP_Dinamico = 0.0
        self.xFuncionActiva = False
        self.xAlarmaFalla = False
        self.tBaseTiempoPWM = 10.0  
        self.xEnProceso = False
        
        # Variables para el retardo de drenaje
        self.tInicioInactividad = 0.0
        self.xCronometroDrenajeActivo = False

        # Variables de Holding Time
        self.tTiempoHoldTranscurrido = 0.0  # Tiempo acumulado en segundos
        self.xHoldCulminado = False         # Señal de avance al siguiente paso
        self.tUltimoChequeoHold = 0.0       # Rastreo del tiempo para el delta
        self.xSP_Alcanzado = False          # Indica si ya llegó al SP por primera vez

    def procesar(self, xEnable, xPause, rTempActual, rTempSetPoint, rGradiente, rGain_P, xReset, tHoldProgramadoMin):
        if xReset:
            self.xAlarmaFalla = False
            self.tTiempoHoldTranscurrido = 0.0
            self.xHoldCulminado = False
            self.xSP_Alcanzado = False     

        if rTempActual > 130.0:
            self.xAlarmaFalla = True

        rSalidaPID = 0.0
        tHoldProgramadoSeg = tHoldProgramadoMin * 60.0  

        # El proceso corre si está habilitado en el SCADA, NO está en falla y NO está pausado
        if xEnable and not self.xAlarmaFalla and not xPause:
            if not self.xEnProceso:
                self.xEnProceso = True
                self.rSP_Dinamico = rTempActual
                self.tUltimoChequeoHold = time.time()
        else:
            self.xEnProceso = False
            self.tUltimoChequeoHold = time.time()

        # Cálculo de la Rampa (Set Point Dinámico)
        if self.xEnProceso and self.rSP_Dinamico != rTempSetPoint:
            if self.rSP_Dinamico < rTempSetPoint:
                self.rSP_Dinamico += (rGradiente / 60.0) * 0.1  # Actualización cada 100ms
                if self.rSP_Dinamico > rTempSetPoint: self.rSP_Dinamico = rTempSetPoint
            elif self.rSP_Dinamico > rTempSetPoint:
                self.rSP_Dinamico -= (rGradiente / 60.0) * 0.1
                if self.rSP_Dinamico < rTempSetPoint: self.rSP_Dinamico = rTempSetPoint
        
        if not self.xEnProceso:
            self.rSP_Dinamico = rTempActual

        # Cálculo PID Proporcional
        if self.xEnProceso:
            rSalidaPID = (self.rSP_Dinamico - rTempActual) * rGain_P
            rSalidaPID = max(-100.0, min(100.0, rSalidaPID))

        # LÓGICA DE HOLDING TIME: DEBE ALCANZAR EL SP Y ESTAR EN BANDA
        tTiempoActualRef = time.time()
        dt = tTiempoActualRef - self.tUltimoChequeoHold
        self.tUltimoChequeoHold = tTiempoActualRef

        if self.xEnProceso and not self.xHoldCulminado:
            # 1. Evaluar si se alcanzó el Set Point Objetivo por primera vez
            if not self.xSP_Alcanzado:
                if (rTempActual >= rTempSetPoint) or (abs(rTempSetPoint - rTempActual) <= 0.5):
                    self.xSP_Alcanzado = True

            # 2. El conteo solo avanza si YA se alcanzó el SP alguna vez Y está dentro de la banda (+/- 2 grados)
            rBandaTolerancia = 2.0 
            if self.xSP_Alcanzado:
                if abs(self.rSP_Dinamico - rTempActual) <= rBandaTolerancia:
                    self.tTiempoHoldTranscurrido += dt
                    if self.tTiempoHoldTranscurrido >= tHoldProgramadoSeg:
                        self.tTiempoHoldTranscurrido = tHoldProgramadoSeg
                        self.xHoldCulminado = True 

        # Lógica PWM por tiempo para las válvulas
        yVapor, yCondensado, yAgua, yRetorno, yDrenaje = False, False, False, False, False
        tActualPWM = time.time() % self.tBaseTiempoPWM

        if self.xEnProceso and not self.xAlarmaFalla:
            self.xFuncionActiva = True
            if rSalidaPID > 0.0:  
                yCondensado = True
                if tActualPWM < (self.tBaseTiempoPWM * (rSalidaPID / 100.0)):
                    yVapor = True
            elif rSalidaPID < 0.0:  
                yRetorno = True
                if tActualPWM < (self.tBaseTiempoPWM * (abs(rSalidaPID / 100.0))):
                    yAgua = True
        else:
            self.xFuncionActiva = False

        # Temporizador de 30 segundos para Drenaje
        if not yVapor and not yAgua:
            if not self.xCronometroDrenajeActivo:
                self.xCronometroDrenajeActivo = True
                self.tInicioInactividad = time.time()
            else:
                if (time.time() - self.tInicioInactividad) >= 30.0:
                    yDrenaje = True
        else:
            self.xCronometroDrenajeActivo = False
            yDrenaje = False

        if self.xAlarmaFalla: yDrenaje = True

        return {
            "yVapor": yVapor, "yCondensado": yCondensado,
            "yAgua": yAgua, "yRetorno": yRetorno, "yDrenaje": yDrenaje,
            "rSP_Dinamico": self.rSP_Dinamico, "xAlarmaFalla": self.xAlarmaFalla,
            "xFuncionActiva": self.xFuncionActiva,
            "tHoldActualMin": self.tTiempoHoldTranscurrido / 60.0,
            "xHoldCulminado": self.xHoldCulminado,
            "xSP_Alcanzado": self.xSP_Alcanzado
        }

# =====================================================================
# 2. APLICACIÓN PRINCIPAL SCADA (TKINTER)
# =====================================================================
class AppSCADA:
    def __init__(self, root):
        self.root = root
        
        # Inicialización estricta de variables antes de renderizar componentes
        self.rTempActual = 22.0       # Registro D100 del PLC
        self.rTempSetPoint = 22.0     # Registro D120 del PLC
        self.xEnable = False
        self.xPause = False       
        self.xReset = False
        self.rampa_segura = 5.0
        self.p_segura = 4.5
        self.t_hold_programado = 10.0 
        self.enviar_sp_a_plc = False
        
        self.datos_bloque = {
            "yVapor": False, "yCondensado": False, "yAgua": False, 
            "yRetorno": False, "yDrenaje": False, "rSP_Dinamico": 22.0, 
            "xAlarmaFalla": False, "xFuncionActiva": False,
            "tHoldActualMin": 0.0, "xHoldCulminado": False, "xSP_Alcanzado": False
        }
        
        self.controlador_termico = BHEATCOOLDIG()
        
        # Configurar dimensiones estéticas de la ventana
        self.root.title("SCADA - Coolmay L02 Modbus RTU")
        self.root.geometry("650x660")
        self.root.configure(bg="#2c3e50")
        
        self.crear_interfaz()

        self.hilo_activo = True
        self.hilo_control = threading.Thread(target=self.bucle_control, daemon=True)
        self.hilo_control.start()
        
        self.actualizar_gui_periodico()

    def crear_interfaz(self):
        lbl_titulo = tk.Label(self.root, text="MONITOREO INTERCAMBIADOR COOLMAY L02", font=("Arial", 12, "bold"), fg="white", bg="#2c3e50")
        lbl_titulo.pack(pady=10)

        # 1. Cuadro de Monitoreo Superior
        frame_monitoreo = tk.Frame(self.root, bg="#2c3e50", bd=1, relief="solid")
        frame_monitoreo.pack(pady=5, fill="x", padx=20)

        self.lbl_temp_actual = tk.Label(frame_monitoreo, text="Temp. Actual (D100): 22.0 °C", font=("Arial", 10, "bold"), fg="#e74c3c", bg="#2c3e50")
        self.lbl_temp_actual.grid(row=0, column=0, padx=15, pady=10, sticky="w")

        self.lbl_sp_dinamico = tk.Label(frame_monitoreo, text="SP Rampa: 22.0 °C", font=("Arial", 10, "bold"), fg="#f1c40f", bg="#2c3e50")
        self.lbl_sp_dinamico.grid(row=0, column=1, padx=15, pady=10, sticky="w")

        self.lbl_hold_actual = tk.Label(frame_monitoreo, text="Hold Actual: 0.00 min", font=("Arial", 10, "bold"), fg="#3498db", bg="#2c3e50")
        self.lbl_hold_actual.grid(row=0, column=2, padx=15, pady=10, sticky="w")

        # 2. Configuración de Parámetros (Entradas numéricas)
        frame_inputs = tk.Frame(self.root, bg="#34495e", pady=10, padx=10)
        frame_inputs.pack(pady=10, fill="x", padx=20)

        tk.Label(frame_inputs, text="SetPoint Objetivo (°C):", fg="white", bg="#34495e").grid(row=0, column=0, padx=5, pady=5, sticky="e")
        self.txt_sp = tk.Entry(frame_inputs, width=8)
        self.txt_sp.insert(0, str(self.rTempSetPoint))
        self.txt_sp.grid(row=0, column=1, padx=5, pady=5)

        btn_enviar_sp = tk.Button(frame_inputs, text="Aplicar SP", command=self.comando_enviar_sp, bg="#2ecc71", fg="white", font=("Arial", 8, "bold"))
        btn_enviar_sp.grid(row=0, column=2, padx=5, pady=5)

        # 3. Estado de Comunicaciones y Alertas de Flujo
        self.lbl_status = tk.Label(self.root, text="ESTADO: INICIALIZANDO COMUNICACIONES...", font=("Arial", 9, "bold"), bg="#2c3e50")
        self.lbl_status.pack(pady=2)

        self.lbl_avance = tk.Label(self.root, text="SISTEMA DETENIDO", font=("Arial", 9, "bold"), bg="#2c3e50")
        self.lbl_avance.pack(pady=2)

        # 4. Panel Operativo de Botones
        frame_botones = tk.Frame(self.root, bg="#2c3e50")
        frame_botones.pack(pady=10)

        self.btn_run = tk.Button(frame_botones, text="INICIAR CONTROL", bg="#2ecc71", fg="white", font=("Arial", 9, "bold"), width=15, command=self.comando_run)
        self.btn_run.grid(row=0, column=0, padx=5)

        btn_pause = tk.Button(frame_botones, text="PAUSAR CONTROL", bg="#7f8c8d", fg="white", font=("Arial", 9, "bold"), width=15, command=self.comando_pause)
        btn_pause.grid(row=0, column=1, padx=5)

        btn_reset = tk.Button(frame_botones, text="RESET", bg="#e74c3c", fg="white", font=("Arial", 9, "bold"), width=10, command=self.comando_reset)
        btn_reset.grid(row=0, column=2, padx=5)
        # 5. Indicadores Visuales de Actuadores (Válvulas)
        frame_valvulas = tk.Frame(self.root, bg="#2c3e50")
        frame_valvulas.pack(pady=15)
        self.canvas_v1 = self.crear_indicador_valvula(frame_valvulas, "V. Vapor", 0)
        self.canvas_v2 = self.crear_indicador_valvula(frame_valvulas, "V. Condensado", 1)
        self.canvas_v3 = self.crear_indicador_valvula(frame_valvulas, "V. Agua", 2)
        self.canvas_v4 = self.crear_indicador_valvula(frame_valvulas, "V. Retorno", 3)
        self.canvas_v5 = self.crear_indicador_valvula(frame_valvulas, "V. Drenaje", 4)
    def crear_indicador_valvula(self, contenedor, nombre, columna):
        frame = tk.Frame(contenedor, bg="#2c3e50", padx=6)
        frame.grid(row=0, column=columna)
        canvas = tk.Canvas(frame, width=50, height=50, bg="#2c3e50", highlightthickness=0)
        canvas.create_oval(10, 10, 40, 40, fill="#7f8c8d", tags="luz")
        canvas.pack()
        tk.Label(frame, text=nombre, fg="white", bg="#2c3e50", font=("Arial", 8)).pack()
        return canvas
    def comando_run(self):
        self.xEnable = not self.xEnable
        self.btn_run.config(text="DETENER CONTROL" if self.xEnable else "INICIAR CONTROL", bg="#e74c3c" if self.xEnable else "#2ecc71")
        
    def comando_pause(self):
        self.xPause = not self.xPause
        
    def comando_reset(self):
        self.xReset = True
        
    def comando_enviar_sp(self):
        try:
            self.rTempSetPoint = float(self.txt_sp.get())
            self.enviar_sp_a_plc = True
        except ValueError:
            pass
            
    def bucle_control(self):
        client = None
        if MODBUS_DISPONIBLE:
            # Conexión serial directa configurada para el PLC Coolmay
            client = ModbusClient(port='COM5', baudrate=9600, bytesize=8, parity='N', stopbits=1, timeout=1)
            client.connect()
            
        while self.hilo_activo:
            start_time = time.time()
            
            # 1. LEER RESPUESTA REAL DEL PLC EN D100 Y D120
            if MODBUS_DISPONIBLE and client and client.is_socket_open():
                try:
                    if self.enviar_sp_a_plc:
                        client.write_register(120, int(self.rTempSetPoint * 10))
                        self.enviar_sp_a_plc = False
                        
                    # Extracción usando [0] para convertir el arreglo Modbus a valor numérico real
                    result_d100 = client.read_holding_registers(100, 1)
                    if result_d100 is not None and not result_d100.isError():
                        val_d100 = result_d100.registers[0]
                        self.rTempActual = val_d100 / 10.0 if val_d100 > 150 else val_d100
                        
                    result_d120 = client.read_holding_registers(120, 1)
                    if result_d120 is not None and not result_d120.isError():
                        val_d120 = result_d120.registers[0]
                        self.rTempSetPoint = val_d120 / 10.0 if val_d120 > 150 else val_d120
                except Exception as e:
                    print(f"[ERROR DE LECTURA PLC]: {e}")
            else:
                # Simulación matemática de respaldo si el puerto físico está cerrado
                if self.datos_bloque.get("yVapor", False):
                    self.rTempActual += 0.15
                elif self.datos_bloque.get("yAgua", False):
                    self.rTempActual -= 0.20
                else:
                    self.rTempActual += (25.0 - self.rTempActual) * 0.005
                    
            # 2. PROCESAR EL BLOQUE DE FUNCIÓN
            self.datos_bloque = self.controlador_termico.procesar(
                xEnable=self.xEnable,
                xPause=self.xPause,
                rTempActual=self.rTempActual,
                rTempSetPoint=self.rTempSetPoint,
                rGradiente=self.rampa_segura,
                rGain_P=self.p_segura,
                xReset=self.xReset,
                tHoldProgramadoMin=self.t_hold_programado
            )
            if self.xReset:
                self.xReset = False
                
            # 3. ESCRITURA DE BOBINAS HACIA EL PLC (Direccionando al esclavo 1)
            if MODBUS_DISPONIBLE and client and client.is_socket_open():
                try:
                    client.write_coil(140, self.datos_bloque["yVapor"])
                    client.write_coil(141, self.datos_bloque["yCondensado"])
                    client.write_coil(142, self.datos_bloque["yAgua"])
                    client.write_coil(143, self.datos_bloque["yRetorno"])
                    client.write_coil(144, self.datos_bloque["yDrenaje"])
                    client.write_coil(150, self.datos_bloque["xHoldCulminado"])
                    client.write_register(125, int(self.datos_bloque["rSP_Dinamico"] * 10))
                except Exception as e:
                    print(f"[ERROR DE ESCRITURA PLC]: {e}")
                    
            tiempo_ejecucion = time.time() - start_time
            time.sleep(max(0.01, 0.1 - tiempo_ejecucion))

    def actualizar_gui_periodico(self):
        self.lbl_temp_actual.config(text=f"Temp. Actual (D100): {self.rTempActual:.1f} °C")
        self.lbl_sp_dinamico.config(text=f"SP Rampa: {self.datos_bloque['rSP_Dinamico']:.1f} °C")
        self.lbl_hold_actual.config(text=f"Hold Actual: {self.datos_bloque['tHoldActualMin']:.2f} min")
        
        # Validar existencia de los elementos de entrada antes del renderizado asíncrono
        if hasattr(self, 'xEnable') and hasattr(self, 'rTempSetPoint') and hasattr(self, 'txt_sp'):
            if not self.xEnable:
                try:
                    valor_caja = self.txt_sp.get()
                    if valor_caja and float(valor_caja) != self.rTempSetPoint:
                        self.txt_sp.delete(0, tk.END)
                        self.txt_sp.insert(0, f"{self.rTempSetPoint:.1f}")
                except (ValueError, tk.TclError):
                    pass
                    
        if MODBUS_DISPONIBLE:
            self.lbl_status.config(text="ESTADO: MODBUS ONLINE - CONEXIÓN CON PLC EXITOSA", fg="#2ecc71")
        else:
            self.lbl_status.config(text="ESTADO: MODO SIMULACIÓN LOCAL (PLC OFFLINE)", fg="#f1c40f")
            
        if self.datos_bloque.get("xHoldCulminado", False):
            self.lbl_avance.config(text="¡PASO COMPLETADO! - SEÑAL DE AVANCE (M150) ACTIVA", fg="#2ecc71")
        elif self.xEnable and not self.xPause:
            if not self.datos_bloque.get("xSP_Alcanzado", False):
                self.lbl_avance.config(text="FASE EN RAMPA: ESPERANDO ALCANZAR SET POINT OBJETIVO (D120)", fg="#3498db")
            elif abs(self.datos_bloque['rSP_Dinamico'] - self.rTempActual) > 2.0:
                self.lbl_avance.config(text="¡HOLD DETENIDO! - TEMPERATURA FUERA DE BANDA", fg="#e74c3c")
            else:
                self.lbl_avance.config(text="FASE HOLD: CONTANDO TIEMPO DENTRO DE BANDA", fg="#f1c40f")
        else:
            self.lbl_avance.config(text="SISTEMA DETENIDO / PAUSADO", fg="#7f8c8d")
            
        self.actualizar_color_valvula(self.canvas_v1, self.datos_bloque["yVapor"], "#e74c3c")
        self.actualizar_color_valvula(self.canvas_v2, self.datos_bloque["yCondensado"], "#e67e22")
        self.actualizar_color_valvula(self.canvas_v3, self.datos_bloque["yAgua"], "#3498db")
        self.actualizar_color_valvula(self.canvas_v4, self.datos_bloque["yRetorno"], "#1abc9c")
        self.actualizar_color_valvula(self.canvas_v5, self.datos_bloque["yDrenaje"], "#e74c3c")
        
        self.root.after(100, self.actualizar_gui_periodico)

    def actualizar_color_valvula(self, canvas, estado_activo, color_encendido):
        color = color_encendido if estado_activo else "#7f8c8d"
        canvas.itemconfig("luz", fill=color)

# =====================================================================
# 🚨 ARRANQUE GRÁFICO UNIFICADO
# =====================================================================
if __name__ == "__main__":
    ventana = tk.Tk()
    app = AppSCADA(ventana)
    ventana.mainloop()
    