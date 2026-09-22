import time
from pymodbus.client import ModbusSerialClient

# CONFIGURACIÓN DEL PUERTO SERIAL (FIJO EN COM5)
client = ModbusSerialClient(
    port='COM5',         # <--- Fijo en tu puerto COM real
    baudrate=19200,      
    parity='N',          
    stopbits=1,          
    bytesize=8,          
    timeout=2            
)

def probar_escritura_m50():
    if not client.connect():
        print("❌ No se pudo abrir el puerto RS-485 en el COM5. Verifica la conexión.")
        return

    id_esclavo = 1
    direccion_m50 = 50  # Dirección nativa base 0 para el relé M50

    try:
        # 1. ENCENDER EL RELÉ M50
        print(f"🔄 [PASO 1] Enviando comando para ACTIVAR M50 en COM5...")
        time.sleep(0.2) # Pausa de estabilización física de la línea
        
        # Enviamos un pulso True (ON) usando la función write_coil (Función Modbus 05)
        res_on = client.write_coil(
            address=direccion_m50, 
            value=True, 
            device_id=id_esclavo
        )
        
        if res_on is None or res_on.isError():
            print(f"❌ El PLC no respondió al comando de activación: {res_on}")
            print("💡 Tip: Si no responde, verifica que el switch físico de la CPU esté en modo 'RUN'.")
        else:
            print("🟢 ¡Comando enviado con éxito! M50 debería estar ENCENDIDO en tu PLC.")
            print("⏳ Manteniendo el estado por 4 segundos... Revisa el monitor de GX Works 2.")
            time.sleep(4)
            
            # 2. APAGAR EL RELÉ M50
            print(f"🔄 [PASO 2] Enviando comando para DESACTIVAR M50...")
            res_off = client.write_coil(
                address=direccion_m50, 
                value=False, 
                device_id=id_esclavo
            )
            
            if res_off is None or res_off.isError():
                print(f"❌ Falló el comando de apagado: {res_off}")
            else:
                print("🛑 ¡Comando enviado con éxito! M50 debería estar APAGADO.")

    except Exception as e:
        print(f"💥 Ocurrió un error inesperado al escribir el bit: {e}")
    finally:
        client.close()

if __name__ == "__main__":
    probar_escritura_m50()
