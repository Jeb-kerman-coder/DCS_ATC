import pygame
import time

pygame.init()
pygame.joystick.init()

joysticks = []

for i in range(pygame.joystick.get_count()):
    joystick = pygame.joystick.Joystick(i)
    joysticks.append(joystick)

    print(
        f"[{i}] {joystick.get_name()} "
        f"({joystick.get_numbuttons()} buttons)"
    )

print()
print("Press buttons on the TWCS.")
print("CTRL+C to stop.")
print()

try:
    while True:

        for event in pygame.event.get():

            if event.type == pygame.JOYBUTTONDOWN:

                joystick = joysticks[event.joy]

                print(
                    f"BUTTON DOWN  | "
                    f"Device [{event.joy}] "
                    f"{joystick.get_name()} | "
                    f"Button {event.button}"
                )

            elif event.type == pygame.JOYBUTTONUP:

                joystick = joysticks[event.joy]

                print(
                    f"BUTTON UP    | "
                    f"Device [{event.joy}] "
                    f"{joystick.get_name()} | "
                    f"Button {event.button}"
                )

        time.sleep(0.005)

except KeyboardInterrupt:

    print("\nStopped.")

finally:

    pygame.quit()