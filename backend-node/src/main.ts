import { Logger, ValidationPipe } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { NestFactory } from '@nestjs/core';
import { FastifyAdapter, NestFastifyApplication } from '@nestjs/platform-fastify';
import { DocumentBuilder, SwaggerModule } from '@nestjs/swagger';
import { ValidationError } from 'class-validator';

import { AppModule } from './app.module';
import { ApiException } from './common/api-exception';
import { ErrorLogService } from './common/error-log.service';
import { ProblemFilter } from './common/problem.filter';

/** Flattens class-validator output into the {field: message} map the portals render beside inputs. */
function toFields(errors: ValidationError[], prefix = ''): Record<string, string> {
  const fields: Record<string, string> = {};
  for (const error of errors) {
    const path = prefix ? `${prefix}.${error.property}` : error.property;
    const first = error.constraints ? Object.values(error.constraints)[0] : undefined;
    if (first && !(path in fields)) fields[path] = first;
    if (error.children?.length) Object.assign(fields, toFields(error.children, path));
  }
  return fields;
}

async function bootstrap(): Promise<void> {
  const app = await NestFactory.create<NestFastifyApplication>(
    AppModule,
    new FastifyAdapter({
      // The gateways and nginx sit in front of this service, so the client address and protocol
      // arrive in X-Forwarded-* headers; without this every request looks like it came from nginx.
      trustProxy: true,
    }),
  );

  app.useGlobalPipes(
    new ValidationPipe({
      whitelist: true,
      forbidNonWhitelisted: true,
      transform: true,
      // Without this, a validation failure leaves as Nest's {statusCode, message[]} and the portals
      // cannot show which field was wrong.
      exceptionFactory: (errors) => ApiException.validation(toFields(errors as ValidationError[])),
    }),
  );

  // Resolved from the container rather than constructed, so it shares the single Prisma connection.
  app.useGlobalFilters(new ProblemFilter(app.get(ErrorLogService)));

  const config = app.get(ConfigService);

  const swagger = new DocumentBuilder()
    .setTitle('API Gateway platform (Node)')
    .setDescription(
      'NestJS control plane. Serves the same contract as backend-java against the same database.',
    )
    .setVersion('0.1.0')
    .addBearerAuth()
    .build();
  SwaggerModule.setup('swagger-ui.html', app, SwaggerModule.createDocument(app, swagger));

  const port = config.get<number>('PORT', 8089);
  // 0.0.0.0, not localhost: inside a container, binding the loopback makes the service unreachable
  // from anywhere else in the compose network.
  await app.listen({ port, host: '0.0.0.0' });
  new Logger('Bootstrap').log(`Node control plane listening on :${port}`);
}

void bootstrap();
