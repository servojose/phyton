# -*- coding: utf-8 -*-
import tkinter as tk
from tkinter import ttk, messagebox
import os
from datetime import datetime
import threading
import time
import pandas as pd
import serial  # <- NUEVO: Comunicación con hardware
import re      # <- NUEVO: Procesamiento de datos seriales


class Sistema40PuntosDinamico:
    def __init__(self, root):
        self.root = root
        self.root.title("REVISADORA TEXTIL INDUSTRIAL - SISTEMA DINÁMICO DE 40 PUNTOS")
        self.root.geometry("1250x760")
        self.root.configure(bg="#1e222b")
        
        # Bloque de maximizado seguro
        try:
            self.root.state('zoomed')
        except Exception:
            pass
        
        # Variables de control de la máquina
        self.metro_actual = 0.0
        self.velocidad_operacion = 20.0
        self.corriendo = False  
        self.hilo_activo = True
        self.defectos_registrados = []
         # ──> NUEVO: Inicializar referencias de botones para evitar errores de hilos
        self.btn_inicio = None
        self.btn_parada = None
        
        # Variable de control de penalización discreta seleccionable (K1 a K4)
        self.valor_k_actual = 1
        
        # DICCIONARIO PARA CONTROLAR FALLAS CONTINUAS EN PROGRESO
        self.fallas_continuas_activas = {}
        
        # =========================================================================
        # NUEVO -> HARDWARE: Variables de control de comunicación con el Arduino
        # =========================================================================
        self.puerto_com = 'COM3'  # Cambia por tu puerto activo si es necesario
        self.baudios = 9600
        self.arduino = None
        self.var_ancho_hardware = tk.StringVar(value="50 cm")
        self.var_estado_hardware = tk.StringVar(value="DESCONECTADO")
        
        # Rutas absolutas para tu directorio en D:\REVISION1
        self.ruta_datos = r"D:\REVISION1\proyecto_analytics_crisp\data\01_raw"
        self.archivo_csv = os.path.join(self.ruta_datos, "historico_rollos_40puntos.csv")
        
        self.construir_interfaz_grafica()
        
        # Iniciar el hilo del simulador del encoder en segundo plano
                # Iniciar el hilo del simulador del encoder en segundo plano
        self.hilo_encoder = threading.Thread(target=self.simular_encoder_metros, daemon=True)
        self.hilo_encoder.start()
      
        # <- NUEVO: Control de Modos iniciales antes de conectar
        self.var_estado_hardware = tk.StringVar(value="DESCONECTADO")
        self.modo_operacion = "MANUAL"
        self.var_modo_visual = tk.StringVar(value="MODO: MANUAL (SW)")

        # <- NUEVO: Intentar conectar el Arduino Uno al arrancar
        self.conectar_arduino_hardware()

    def conectar_arduino_hardware(self):
       
     
        """Inicializa el canal serial de forma segura sin congelar la interfaz"""
        try:
            self.arduino = serial.Serial(port=self.puerto_com, baudrate=self.baudios, timeout=1)
            time.sleep(2)  
            self.var_estado_hardware.set("CONECTADO")
            
            hilo_hw = threading.Thread(target=self.leer_puerto_serial_arduino, daemon=True)
            hilo_hw.start()
        except Exception as e:
            print(f"Hardware: No se detectó placa en {self.puerto_com}. Modo simulación activo. {e}")
            self.var_estado_hardware.set("MODO SIMULADO")

    def simular_encoder_metros(self):
        """Simula el paso de la tela a través del rodillo medidor"""
        while self.hilo_activo:
            time.sleep(0.1)
            if self.corriendo:
                self.metro_actual += (self.velocidad_operacion / 60) * 0.1
                self.lbl_metros_digital.config(text=f"{round(self.metro_actual, 2)} m")
 
    def leer_puerto_serial_arduino(self):
   
        """Procesa la telemetría unificada de Arduino soportando formato con '|' o con ','"""
        while self.arduino and self.arduino.is_open:
            if self.arduino.in_waiting > 0:
                try:
                    linea_bytes = self.arduino.readline()
                    linea_texto = linea_bytes.decode('utf-8', errors='ignore').strip()
                    
                    if not linea_texto or ":" not in linea_texto:
                        continue
                        
                    # IMPRESIÓN DE CONTROL: Esto te mostrará en la terminal exactamente qué está llegando
                    print(f"HARDWARE RAW -> {linea_texto}")

                    # Normalizamos la línea: si viene con barras '|', las convertimos en comas ','
                    linea_limpia = linea_texto.replace("|", ",")
                    
                    # Convertimos la cadena en un diccionario Python de forma segura
                    datos = {}
                    for item in linea_limpia.split(","):
                        if ":" in item:
                            k, v = item.split(":", 1)
                            datos[k.strip().replace("MÁQ", "MAQ")] = v.strip()

                    # =========================================================================
                    # 1. ACTUALIZACIÓN DE MODO (AUTOMÁTICO / MANUAL)
                    # =========================================================================
                    modo_hw = datos.get("Modo")
                    if modo_hw and self.modo_operacion != modo_hw:
                        self.modo_operacion = "AUTOMATICO" if modo_hw == "AUTO" else "MANUAL"
                        
                        if modo_hw == "AUTO":
                            self.root.after(0, self.var_modo_visual.set, "MODO: AUTOMÁTICO")
                            self.root.after(0, lambda: self.lbl_modo_status.config(
                                textvariable="", text="MODO: AUTOMÁTICO", bg="#61afef", fg="#1e222b"
                            ))
                            if hasattr(self, 'btn_inicio') and hasattr(self, 'btn_parada'):
                                if self.btn_inicio and self.btn_parada:
                                    self.root.after(0, lambda: self.btn_inicio.config(state="disabled", bg="#5c6370"))
                                    self.root.after(0, lambda: self.btn_parada.config(state="disabled", bg="#5c6370"))
                        else:
                            self.root.after(0, self.var_modo_visual.set, "MODO: MANUAL (SW)")
                            self.root.after(0, lambda: self.lbl_modo_status.config(
                                textvariable="", text="MODO: MANUAL (SW)", bg="#d19a66", fg="black"
                            ))
                            if hasattr(self, 'btn_inicio') and hasattr(self, 'btn_parada'):
                                if self.btn_inicio and self.btn_parada:
                                    self.root.after(0, lambda: self.btn_inicio.config(state="normal", bg="#28a745"))
                                    self.root.after(0, lambda: self.btn_parada.config(state="normal", bg="#dc3545"))

                    # =========================================================================
                    # 2. ACTUALIZACIÓN DEL ANCHO REAL (Muestra en cm)
                    # =========================================================================
                    ancho_hw = datos.get("Ancho")
                    if ancho_hw:
                        try:
                            ancho_centimetros = int(float(ancho_hw) * 100)
                            self.root.after(0, self.var_ancho_hardware.set, f"{ancho_centimetros} cm")
                        except ValueError:
                            pass

                    # =========================================================================
                    # 3. INTERRUPCIÓN GRÁFICA POR SENTIDO DE GIRO
                    # =========================================================================
                    sentido_hw = datos.get("Sentido")
                    if sentido_hw == "RETROCESO":
                        if hasattr(self, 'btn_pausa') and self.btn_pausa:
                            self.root.after(0, lambda: self.btn_pausa.config(text="◀ RETROCESO", bg="#ffc107", fg="black"))
                    elif sentido_hw == "ADELANTE":
                        if hasattr(self, 'btn_pausa') and self.btn_pausa:
                            self.root.after(0, lambda: self.btn_pausa.config(text="▶ ADELANTE", bg="#abb2bf", fg="black"))

                    # =========================================================================
                    # 4. SINCRONIZACIÓN DEL ESTADO DE MARCHA (MAQ)
                    # =========================================================================
                    estado_maquina_hw = datos.get("MAQ")
                    if estado_maquina_hw == "MARCHA":
                        self.corriendo = True
                        self.root.after(0, lambda: self.var_testigo_hw.set("TESTIGO: MARCHA ▶"))
                        self.root.after(0, lambda: self.lbl_testigo_botones.config(bg="#28a745", fg="white"))
                        self.root.after(0, lambda: self.lbl_estado_maquina.config(
                            text="MAQUINA: RETROCESO ▶" if sentido_hw == "RETROCESO" else "MAQUINA: MARCHA ▶", 
                            fg="#ffc107" if sentido_hw == "RETROCESO" else "#28a745"
                        ))
                            
                    elif estado_maquina_hw == "PARADA":
                        self.corriendo = False
                        self.root.after(0, lambda: self.var_testigo_hw.set("TESTIGO: PARADA ⏹"))
                        self.root.after(0, lambda: self.lbl_testigo_botones.config(bg="#4b5563", fg="white"))
                        self.root.after(0, lambda: self.lbl_estado_maquina.config(
                            text="MAQUINA: ESPERA INICIO" if sentido_hw == "RETROCESO" else "MAQUINA: PARADA", 
                            fg="#ffc107" if sentido_hw == "RETROCESO" else "#abb2bf"
                        ))
                            
                    elif estado_maquina_hw == "EMERGENCIA":
                        self.corriendo = False
                        self.root.after(0, lambda: self.var_testigo_hw.set("¡¡EMERGENCIA ACTIVA!! 🚨"))
                        self.root.after(0, lambda: self.lbl_testigo_botones.config(bg="#dc3545", fg="white"))
                        self.root.after(0, lambda: self.lbl_estado_maquina.config(text="MÁQ: EMERGENCIA", fg="#e06c75"))

                except Exception as e:
                    print(f"Error procesando datos de telemetría serial: {e}")
 
     
    def alternar_modo_operacion(self, nuevo_modo):
        """Alterna el control de la máquina entre los comandos de la interfaz y los switches del Arduino"""
        self.modo_operacion = nuevo_modo
        if nuevo_modo == "MANUAL":
            self.var_modo_visual.set("MODO: MANUAL (SW)")
            self.lbl_modo_status.config(bg="#d19a66", fg="black")
            # Forzamos una pausa inicial al cambiar a manual por seguridad
            self.boton_pausa_maquina()
        else:
            self.var_modo_visual.set("MODO: AUTOMÁTICO")
            self.lbl_modo_status.config(bg="#61afef", fg="#1e222b")
    def cambiar_indicador_k(self, nuevo_k):
        """Modifica dinámicamente la severidad discreta y actualiza la alerta visual"""
        self.valor_k_actual = nuevo_k
        for k_val, btn in self.botones_k.items():
            btn.config(relief="raised", bd=2)
        
        self.botones_k[1].config(relief="sunken", bd=4)

    #def boton_inicio_maquina(self):
       # """Arranca el conteo del encoder de metraje"""
     #   self.corriendo = True
     #   self.lbl_estado_maquina.config(text="MAQUINA: CORRIENDO", fg="#98c379")
    def boton_inicio_maquina(self):
        """Arranca la máquina enviando START una sola vez (Modo Manual)"""
        if self.modo_operacion == "AUTOMATICO":
            return 

        if self.arduino and self.arduino.is_open:
            try:
                # Limpiamos buffers antes de enviar para evitar datos encolados
                self.arduino.reset_output_buffer()
                self.arduino.write(b"START\n")
                print("[PYTHON -> ARDUINO]: Comando START enviado una vez.")
            except Exception as e:
                print(f"Error al enviar START: {e}")
        
        self.corriendo = True
        self.lbl_estado_maquina.config(text="MAQUINA: CORRIENDO", fg="#98c379")
        
    def boton_parada_maquina(self):
   
        """Detiene la máquina enviando el comando por puerto serie con prioridad absoluta"""
        print("[BOTÓN CLICK] Se presionó PARADA en la interfaz gráfica.")
        
        # Enviamos el comando al Arduino de forma directa e inmediata
        if self.arduino and self.arduino.is_open:
            try:
                self.arduino.reset_output_buffer()
                self.arduino.write(b"STOP\n")
                self.arduino.flush()  # Fuerza la salida inmediata por el cable USB
                print("[PYTHON -> HARDWARE]: STOP enviado con éxito.")
            except Exception as e:
                print(f"Error crítico al enviar STOP al hardware: {e}")

        # Sincronizamos el estado de la interfaz local
        self.corriendo = False
        self.lbl_estado_maquina.config(text="MAQUINA: PARADA", fg="#e06c75")
     
               
    def boton_pausa_maquina(self):
        """Función redefinida de manera segura: la pausa física pasó a ser Retroceso en Hardware"""
        print("[SISTEMA] El botón físico/función de pausa ahora es controlado por la palanca de Retroceso.")
        # Forzar detención local segura si es invocada por error en la interfaz
        if self.corriendo:
            self.boton_parada_maquina()


    def boton_parada_maquina(self):
   
        """Detiene la máquina enviando el comando STOP por el puerto serie"""
        print("[CLICK] Se presionó el botón PARADA en la pantalla.")
        
        if self.arduino and self.arduino.is_open:
            try:
                self.arduino.reset_output_buffer()
                self.arduino.write(b"STOP\n")
                self.arduino.flush()  # Fuerza a Python a escupir el dato por el cable USB ya
                print("[PYTHON -> HARDWARE]: ¡Comando STOP enviado con éxito!")
            except Exception as e:
                print(f"Error al enviar STOP por el puerto serie: {e}")
        else:
            print("[AVISO]: No se envió STOP porque el Arduino está desconectado o simulado.")

        # Sincronización visual local
        self.corriendo = False
        self.lbl_estado_maquina.config(text="MAQUINA: PARADA", fg="#e06c75")

    def boton_reinicio_total(self):
        """Reset industrial: Limpia contadores y tablas para un nuevo rollo"""
        if self.fallas_continuas_activas:
            messagebox.showwarning("Fallas Activas", "Hay tramos continuos abiertos. Ciérralos antes de reiniciar la máquina.")
            return
        
        if messagebox.askyesno("Confirmar Reinicio", "¿Deseas borrar los contadores actuales e iniciar un rollo desde cero?"):
            self.corriendo = False
            self.metro_actual = 0.0
            self.defectos_registrados.clear()
            self.fallas_continuas_activas.clear()
            self.lbl_metros_digital.config(text="0.00 m")
            self.lbl_estado_maquina.config(text="MAQUINA: RESETEADA", fg="#61afef")
            
            for fila in self.tabla.get_children():
                self.tabla.delete(fila)

    def construir_interfaz_grafica(self):
        # Acomodamos las variables aquí mismo para asegurar que existan antes de diseñar la pantalla
        self.modo_operacion = "MANUAL"
        self.var_modo_visual = tk.StringVar(value="MODO: MANUAL (SW)")
                # Variables de control para las luces testigo de comunicación
        self.var_testigo_hw = tk.StringVar(value="TESTIGO SW: ESPERANDO")


        # --- ESTILOS DE LA INTERFAZ ---
        estilo = ttk.Style()
        estilo.theme_use("clam")
        estilo.configure("Treeview", background="#282c34", foreground="white", fieldbackground="#282c34", rowheight=25)
        estilo.map("Treeview", background=[('selected', '#0070C0')])

        # --- PANEL SUPERIOR: DATOS GENERALES Y SENSORES ---
        frame_top = tk.Frame(self.root, bg="#1e222b", bd=2, relief="groove")
        frame_top.pack(fill="x", padx=15, pady=10)

        # Entradas del operador
        lbl_font = ("Arial", 10, "bold")
        tk.Label(frame_top, text="TEJIDO:", fg="#abb2bf", bg="#1e222b", font=lbl_font).grid(row=0, column=0, padx=10, pady=5)
        self.ent_tejido = tk.Entry(frame_top, width=12, font=("Arial", 11))
        self.ent_tejido.grid(row=0, column=1)
        self.ent_tejido.insert(0, "RE80-3")

        tk.Label(frame_top, text="OP:", fg="#abb2bf", bg="#1e222b", font=lbl_font).grid(row=0, column=2, padx=10, pady=5)
        self.ent_op = tk.Entry(frame_top, width=10, font=("Arial", 11))
        self.ent_op.grid(row=0, column=3)
        self.ent_op.insert(0, "1209")

        tk.Label(frame_top, text="ANCHOR (Pulg):", fg="#abb2bf", bg="#1e222b", font=lbl_font).grid(row=0, column=4, padx=10, pady=5)
        self.ent_ancho = tk.Entry(frame_top, width=10, font=("Arial", 11))
        self.ent_ancho.grid(row=0, column=5)
        self.ent_ancho.insert(0, "61.38")

        tk.Label(frame_top, text="KG ROLLO:", fg="#abb2bf", bg="#1e222b", font=lbl_font).grid(row=0, column=6, padx=10, pady=5)
        self.ent_kg = tk.Entry(frame_top, width=10, font=("Arial", 11))
        self.ent_kg.grid(row=0, column=7)
        self.ent_kg.insert(0, "19.84")

        # MARCADOR DIGITAL DE METROS
        tk.Label(frame_top, text="METRAJE RECORRIDO:", fg="#61afef", bg="#1e222b", font=("Arial", 11, "bold")).grid(row=1, column=0, columnspan=2, pady=10)
        self.lbl_metros_digital = tk.Label(frame_top, text="0.00 m", fg="#98c379", bg="#282c34", font=("Arial", 22, "bold"), width=12, relief="sunken")
        self.lbl_metros_digital.grid(row=1, column=2, columnspan=2, pady=10)

        # PANEL DE CONTROL DE MARCHA INDUSTRIAL
        frame_marcha = tk.Frame(frame_top, bg="#1e222b")
        frame_marcha.grid(row=1, column=4, columnspan=4, padx=10, pady=10)

        btn_inicio = tk.Button(frame_marcha, text="▶ INICIO", bg="#28a745", fg="white", font=("Arial", 10, "bold"), width=9, command=self.boton_inicio_maquina)
        btn_inicio.pack(side="left", padx=3)

        btn_pausa = tk.Button(frame_marcha, text="⏸ PAUSA", bg="#ffc107", fg="black", font=("Arial", 10, "bold"), width=9, command=self.boton_pausa_maquina)
        btn_pausa.pack(side="left", padx=3)

        btn_parada = tk.Button(frame_marcha, text="⏹ PARADA", bg="#dc3545", fg="white", font=("Arial", 10, "bold"), width=9, command=self.boton_parada_maquina)
        btn_parada.pack(side="left", padx=3)

        btn_reinicio = tk.Button(frame_marcha, text="🔄 REINICIO", bg="#17a2b8", fg="white", font=("Arial", 10, "bold"), width=9, command=self.boton_reinicio_total)
        btn_reinicio.pack(side="left", padx=3)

        # 1. Estado de la máquina
        self.lbl_estado_maquina = tk.Label(frame_marcha, text="MAQUINA: LISTA", fg="#abb2bf", bg="#1e222b", font=("Arial", 11, "bold"), width=15, anchor="w")
        self.lbl_estado_maquina.pack(side="left", padx=5)

        # 2. Indicador visual del Estado del Hardware
        self.lbl_hw_status = tk.Label(frame_marcha, textvariable=self.var_estado_hardware, fg="#61afef", bg="#282c34", font=("Arial", 9, "bold"), width=15, relief="groove")
        self.lbl_hw_status.pack(side="left", padx=5)

        # 3. ÚNICO Marcador del Ancho Real que lee el Arduino
        self.lbl_ancho_hw = tk.Label(frame_marcha, textvariable=self.var_ancho_hardware, fg="#98c379", bg="#282c34", font=("Arial", 11, "bold"), width=8, relief="sunken")
        self.lbl_ancho_hw.pack(side="left", padx=5)

        # 4. Etiqueta dinámica de Estado de Modo (Manual o Automático)
        self.lbl_modo_status = tk.Label(frame_marcha, textvariable=self.var_modo_visual, fg="#1e222b", bg="#d19a66", font=("Arial", 10, "bold"), width=18, relief="groove")
        self.lbl_modo_status.pack(side="left", padx=5)
                # <- NUEVO: Indicador visual tipo Luz Testigo de comunicación de botones
        self.lbl_testigo_botones = tk.Label(frame_marcha, textvariable=self.var_testigo_hw, fg="white", bg="#4b5563", font=("Arial", 9, "bold"), width=24, relief="groove")
        self.lbl_testigo_botones.pack(side="left", padx=5)


        # --- CONTENEDOR INTERMEDIO ---
        frame_medio = tk.Frame(self.root, bg="#1e222b")
        frame_medio.pack(fill="both", expand=True, padx=15, pady=5)

        # PANEL IZQUIERDO: CUADRO DE MAPEO INTEGRAL FLUIDO (ÚNICO)
        frame_tabla = tk.LabelFrame(frame_medio, text=" Mapeo de Ubicación y Tramos de Fallas ", fg="#61afef", bg="#1e222b", font=("Arial", 11, "bold"))
        frame_tabla.pack(side="left", fill="both", expand=True, padx=10, pady=5)

        self.tabla = ttk.Treeview(frame_tabla, columns=("Hora", "Defecto", "K", "Inicio", "Fin", "Abarcado", "Ancho_D"), show="headings")
        self.tabla.heading("Hora", text="Hora")
        self.tabla.heading("Defecto", text="Defecto")
        self.tabla.heading("K", text="Puntos (K)")
        self.tabla.heading("Inicio", text="Inicio (m)")
        self.tabla.heading("Fin", text="Fin (m)")
        self.tabla.heading("Abarcado", text="Abarcado (m)")
        self.tabla.heading("Ancho_D", text="Ancho (D)")

        self.tabla.column("Hora", width=75, anchor="center")
        self.tabla.column("Defecto", width=120, anchor="w")
        self.tabla.column("K", width=80, anchor="center")
        self.tabla.column("Inicio", width=85, anchor="center")
        self.tabla.column("Fin", width=85, anchor="center")
        self.tabla.column("Abarcado", width=100, anchor="center")
        self.tabla.column("Ancho_D", width=85, anchor="center")
        
        self.tabla.pack(fill="both", expand=True, padx=10, pady=10)
        self.tabla.tag_configure("abierto", background="#ff9f43", foreground="black")

        # =========================================================================
        # PANEL DERECHO: INTERFAZ DE CONTROL COMPACTA
        # =========================================================================
        frame_derecho_master = tk.Frame(frame_medio, bg="#1e222b")
        frame_derecho_master.pack(side="right", fill="y", padx=10, pady=5)

        # Selector de severidad K
        frame_selectores_k = tk.LabelFrame(frame_derecho_master, text=" SEVERIDAD PARA DEFECTOS DISCRETOS ", fg="#e5c07b", bg="#1e222b", font=("Arial", 9, "bold"))
        frame_selectores_k.pack(fill="x", pady=(0, 5))

        self.botones_k = {}
        config_k_botones = [
            (1, "K1 (1 PTO)", "#10b981"), (2, "K2 (2 PTOS)", "#FFC000"),
            (3, "K3 (3 PTOS)", "#d19a66"), (4, "K4 (4 PTOS)", "#C00000")
        ]
        for k_val, txt, color in config_k_botones:
            btn_k = tk.Button(frame_selectores_k, text=txt, bg=color, fg="white", font=("Arial", 9, "bold"), height=1, command=lambda kv=k_val: self.cambiar_indicador_k(kv))
            btn_k.pack(fill="x", padx=15, pady=2)
            self.botones_k[k_val] = btn_k
       
        # BOTONERA GENERAL DE DEFECTOS
        frame_botones = tk.LabelFrame(frame_derecho_master, text=" REGISTRO DE DEFECTOS EN VIVO ", fg="#61afef", bg="#1e222b", font=("Arial", 11, "bold"))
        frame_botones.pack(fill="x", expand=False, pady=5)

        # Celda de distancia a lo ancho genérica superior
        tk.Label(frame_botones, text="Distancia Ancho (D) [0 a 1]:", fg="#abb2bf", bg="#1e222b", font=("Arial", 10, "bold")).pack(pady=(5, 2))
        self.ent_distancia_d = tk.Entry(frame_botones, font=("Arial", 12, "bold"), width=12, justify="center", bg="#282c34", fg="#98c379", insertbackground="white")
        self.ent_distancia_d.pack(pady=(0, 5))
        self.ent_distancia_d.insert(0, "0.3")

        # Lista completa de los 9 defectos reales de la hilandería
        btn_config = [
            ("MANCHAS", False), ("FALLA AGUJA", True), ("HUECOS", False),
            ("CONTAMINACION", True), ("LYCRA", True), ("CAIDAS", False),
            ("GUIA", False), ("BARRADO", True), ("ENGANCHE", False)
        ]

        # Creación fluida de los botones con espaciado compacto industrial
        for text, es_continuo in btn_config:
            lbl_boton = f"{text} 🔁" if es_continuo else text
            color_btn = "#ff9f43" if es_continuo else "#4b5563"
            
            btn = tk.Button(frame_botones, text=lbl_boton, bg=color_btn, fg="white", font=("Arial", 9, "bold"), height=1, width=22)
            btn.config(command=lambda n=text, c=es_continuo, b=btn: self.procesar_registro_defecto(n, c, b))
            btn.pack(fill="x", padx=15, pady=1)

        # --- PANEL INFERIOR: BOTÓN VERDE INDUSTRIAL DE CIERRE ---
        btn_finalizar = tk.Button(self.root, text="FINALIZAR INSPECCIÓN DE ROLLO E IMPRIMIR REPORTE", bg="#00B050", fg="white", font=("Arial", 14, "bold"), height=2, command=self.cerrar_inspeccion_rollo)
        btn_finalizar.pack(side="bottom", fill="x", padx=15, pady=15)
   

    def procesar_registro_defecto(self, nombre_defecto, es_continuo, boton_objeto):
  
        if not self.corriendo:
            messagebox.showwarning("Máquina Detenida", "Debes presionar el botón '▶ INICIO'")
            return

        metro_congelado = round(self.metro_actual, 2)
        hora_exacta = datetime.now().strftime("%H:%M:%S")

        # =========================================================================
        # CONGELAR EL SITIO EXACTO DEL ANCHO DESDE EL HARDWARE EN EL INSTANTE DEL DEFECTO
        # =========================================================================
        try:
            texto_pantalla_ancho = self.var_ancho_hardware.get() # Captura ej: "50 cm" o "1.20 m"
            # Limpiamos el texto para dejar solo los números y la unidad
            distancia_ancho_d = texto_pantalla_ancho.strip()
        except Exception:
            distancia_ancho_d = "0 cm"

        if es_continuo:
            if nombre_defecto not in self.fallas_continuas_activas:
                # Abrir tramo continuo
                iid = self.tabla.insert("", "end", values=(hora_exacta, f"{nombre_defecto}", "En Proceso...", f"{metro_congelado} m", "Abierto", "Corriendo...", distancia_ancho_d), tags=("abierto",))
                self.fallas_continuas_activas[nombre_defecto] = {
                    "metro_inicio": metro_congelado, "hora_inicio": hora_exacta, "ancho_d": distancia_ancho_d, "iid_tabla": iid
                }
                boton_objeto.config(bg="#d32f2f", fg="white", relief="sunken", text=f"{nombre_defecto} 🛑")
            else:
                # Cerrar tramo continuo
                datos_inicio = self.fallas_continuas_activas.pop(nombre_defecto)
                m_inicio = datos_inicio["metro_inicio"]
                m_fin = metro_congelado
                distancia_neto = round(m_fin - m_inicio, 2)
                distancia_yardas = distancia_neto * 1.09361

                if distancia_yardas <= 1.0:
                    k_calculado = 1
                elif distancia_yardas <= 2.0:
                    k_calculado = 2
                elif distancia_yardas <= 3.0:
                    k_calculado = 3
                else:
                    k_calculado = 4
                
                self.tabla.delete(datos_inicio["iid_tabla"])
                # Insertamos el ancho congelado desde el inicio del tramo
                self.tabla.insert("", "end", values=(datos_inicio["hora_inicio"], nombre_defecto, k_calculado, f"{m_inicio} m", f"{m_fin} m", f"{distancia_neto} m", datos_inicio["ancho_d"]))
                
                self.defectos_registrados.append({
                    "hora": datos_inicio["hora_inicio"],
                    "defecto": nombre_defecto,
                    "k": k_calculado,
                    "metro_inicio": m_inicio,
                    "metro_fin": m_fin,
                    "metraje_abarcado": distancia_neto,
                    "ancho_d": datos_inicio["ancho_d"] # Guardado en el historial
                })
                boton_objeto.config(bg="#ff9f43", fg="white", relief="raised", text=f"{nombre_defecto} 🔁")
        else:
            # Defecto discreto instantáneo
            self.tabla.insert("", "end", values=(hora_exacta, nombre_defecto, self.valor_k_actual, f"{metro_congelado} m", f"{metro_congelado} m", "0.0 m", distancia_ancho_d))
            self.defectos_registrados.append({
                "hora": hora_exacta, 
                "defecto": nombre_defecto, 
                "k": self.valor_k_actual,
                "metro_inicio": metro_congelado, 
                "metro_fin": metro_congelado, 
                "metraje_abarcado": 0.0, 
                "ancho_d": distancia_ancho_d # Guardado en el historial
            })

    def cerrar_inspeccion_rollo(self):
        """Manejador del botón de cierre de rollo con validación, cálculo de calidad y guardado en CSV/TXT"""
        if self.fallas_continuas_activas:
            messagebox.showwarning("Fallas en Tránsito", "Hay tramos continuos abiertos. Ciérralos antes de proceder.")
            return

        self.corriendo = False
        self.lbl_estado_maquina.config(text="MAQUINA: FINALIZADO", fg="#00B050")

        # Captura de datos generales del formulario superior
        op_text = self.ent_op.get().strip()
        tejido_text = self.ent_tejido.get().strip()
        
        try:
            ancho_pulg = float(self.ent_ancho.get().strip())
            kg_totales = float(self.ent_kg.get().strip())
        except ValueError:
            messagebox.showerror("Error de Datos", "Por favor verifica que Ancho y Kilos contengan valores numéricos.")
            return

        # Lógica matemática estándar: Sistema de los 40 puntos
        total_puntos_k = sum([d["k"] for d in self.defectos_registrados])
        largo_final_yardas = self.metro_actual * 1.09361
        
        if largo_final_yardas > 0 and ancho_pulg > 0:
            puntos_100_yardas_cuadradas = round((total_puntos_k * 3600) / (largo_final_yardas * ancho_pulg), 2)
            clasificacion_calidad = "APROBADO (Primera Calidad)" if puntos_100_yardas_cuadradas <= 40.0 else "RECHAZADO (Segunda Calidad)"
        else:
            puntos_100_yardas_cuadradas = 0.0
            clasificacion_calidad = "SIN METRAJE SUFICIENTE"

        fecha_hoy = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 1. EXPORTAR DATOS A EXCEL (CSV) MEDIANTE PANDAS
        nuevo_registro = {
            "Fecha": [fecha_hoy], "OP": [op_text], "Tejido": [tejido_text],
            "Ancho_Pulg": [ancho_pulg], "Kg_Rollo": [kg_totales], "Metros_Totales": [round(self.metro_actual, 2)],
            "Yardas_Totales": [round(largo_final_yardas, 2)], "Total_Puntos_K": [total_puntos_k],
            "Puntos_100_Yd2": [puntos_100_yardas_cuadradas], "Calidad": [clasificacion_calidad]
        }
        df_nuevo = pd.DataFrame(nuevo_registro)

        try:
            os.makedirs(self.ruta_datos, exist_ok=True)
            if not os.path.exists(self.archivo_csv):
                df_nuevo.to_csv(self.archivo_csv, index=False, encoding="utf-8")
            else:
                df_nuevo.to_csv(self.archivo_csv, mode='a', header=False, index=False, encoding="utf-8")
            csv_guardado = True
        except Exception as e:
            csv_guardado = False
            messagebox.showerror("Error Base de Datos", f"No se pudo guardar el histórico CSV: {str(e)}")

        # 2. GENERACIÓN E IMPRESIÓN DEL REPORTE FÍSICO (.TXT)
        nombre_reporte_txt = os.path.join(self.ruta_datos, f"Reporte_Calidad_OP_{op_text}_{datetime.now().strftime('%H%M%S')}.txt")
        try:
            with open(nombre_reporte_txt, "w", encoding="utf-8") as f:
                f.write("====================================================\n")
                f.write("        DS TEXTIL, C.A. - REPORTE DE CALIDAD        \n")
                f.write("         SISTEMA DINÁMICO DE 40 PUNTOS             \n")
                f.write("====================================================\n")
                f.write(f"Fecha/Hora:       {fecha_hoy}\n")
                f.write(f"Orden de Prod:    {op_text}\n")
                f.write(f"Código Tejido:    {tejido_text}\n")
                f.write(f"Ancho (Pulgadas): {ancho_pulg} in\n")
                f.write(f"Peso del Rollo:   {kg_totales} kg\n")
                f.write("----------------------------------------------------\n")
                f.write(f"Metraje Final:    {round(self.metro_actual, 2)} m\n")
                f.write(f"Yardaje Final:    {round(largo_final_yardas, 2)} yd\n")
                f.write(f"Total Penalizac:  {total_puntos_k} Puntos K\n")
                f.write(f"PUNTOS X 100 YD²: {puntos_100_yardas_cuadradas} pts\n")
                f.write("----------------------------------------------------\n")
                f.write(f"DIAGNÓSTICO:      {clasificacion_calidad}\n")
                f.write("====================================================\n\n")
                # =========================================================================
                # REEMPLAZA ESTA SECCIÓN DENTRO DE TU FUNCIÓN DE ESCRITURA TXT:
                # =========================================================================
                f.write("DETALLE HISTÓRICO DE DEFECTOS EN EL ROLLO:\n")
                f.write("Hora     | Defecto        | Pts (K) | Sitio Ancho | Ubicación Tramo\n")
                f.write("---------|----------------|---------|-------------|----------------\n")
                for d in self.defectos_registrados:
                    fin_tramo = f"{d.get('metro_fin', 0.0)} m" if d.get('metraje_abarcado', 0.0) > 0 else "Instantáneo"
                    sitio_ancho = d.get('ancho_d', '0 cm')
                    # Estructura alineada con la nueva columna de sitio (Ancho)
                    f.write(f"{d['hora']} | {d['defecto']:<14} | {d['k']:<7} | {sitio_ancho:<11} | {d['metro_inicio']} m -> {fin_tramo}\n")

                #f.write("DETALLE HISTÓRICO DE DEFECTOS EN EL ROLLO:\n")
                #f.write("Hora     | Defecto        | Pts (K) | Ubicación Tramo\n")
               # f.write("---------|----------------|---------|----------------\n")
                #for d in self.defectos_registrados:
                  #  fin_tramo = f"{d.get('metro_fin', 0.0)} m" if d.get('metraje_abarcado', 0.0) > 0 else "Instantáneo"
                  #  f.write(f"{d['hora']} | {d['defecto']:<14} | {d['k']:<7} | {d['metro_inicio']} m -> {fin_tramo}\n")
            
            os.startfile(nombre_reporte_txt)
            txt_guardado = True
        except Exception as e:
            txt_guardado = False
            messagebox.showerror("Error Reporte", f"No se pudo escribir el archivo físico de texto: {str(e)}")

        if csv_guardado and txt_guardado:
            messagebox.showinfo("Inspección Guardada", 
                                f"Rollo procesado con éxito.\n\n"
                                f"• Calificación: {clasificacion_calidad}\n"
                                f"• Puntos/100Yd²: {puntos_100_yardas_cuadradas}\n\n"
                                f"Datos exportados a base de datos e informe enviado a la cola de impresión.")

if __name__ == "__main__":
    root = tk.Tk()
    app = Sistema40PuntosDinamico(root)
    root.mainloop()
   